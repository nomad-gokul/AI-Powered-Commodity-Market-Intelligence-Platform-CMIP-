"""End-to-end extraction API tests against the real app, database, and
Redis (redirected-to-tmp_path local storage, per the autouse fixture in
tests/integration/conftest.py). No real worker runs here - trigger_extraction
enqueues a real ARQ job that nothing consumes in-process, same pattern
Phase 2's reprocess tests use; these cover the API/RBAC surface, not the
pipeline itself (see test_worker_pipeline.py for that).
"""

import uuid

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.auth.models import Role, User
from app.modules.documents.models import Document, DocumentChunk, StorageProviderKind
from app.modules.extraction.api import _resolve_provider_and_model
from app.modules.extraction.domain import compute_extraction_fingerprint
from app.modules.extraction.models import (
    EntityType,
    ExtractedEntity,
    ExtractedTable,
    ExtractionRun,
    ExtractionStatus,
    TableCell,
)
from app.modules.extraction.prompts import get_extraction_prompt_registry

REGISTER_PAYLOAD = {
    "email": "extractor@example.com",
    "full_name": "Test Extractor",
    "password": "a-genuinely-strong-password",
}


async def _promote(session: AsyncSession, email: str, role_name: str) -> None:
    user = (await session.execute(select(User).where(User.email == email))).scalar_one()
    role = (await session.execute(select(Role).where(Role.name == role_name))).scalar_one()
    user.roles.append(role)
    await session.flush()


async def _login(client: AsyncClient, email: str = REGISTER_PAYLOAD["email"]) -> str:
    response = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": REGISTER_PAYLOAD["password"]}
    )
    token: str = response.json()["data"]["access_token"]
    return token


async def _register_and_login(client: AsyncClient, email: str = REGISTER_PAYLOAD["email"]) -> str:
    payload = {**REGISTER_PAYLOAD, "email": email}
    await client.post("/api/v1/auth/register", json=payload)
    return await _login(client, email)


async def _create_document_with_chunk(session: AsyncSession) -> Document:
    document = Document(
        filename="doc.pdf",
        original_filename="doc.pdf",
        extension=".pdf",
        mime_type="application/pdf",
        file_size=100,
        sha256_hash=uuid.uuid4().hex + "0" * 32,
        storage_provider=StorageProviderKind.LOCAL,
        storage_key="doc.pdf",
    )
    session.add(document)
    await session.flush()
    session.add(
        DocumentChunk(
            document_id=document.id,
            chunk_index=0,
            page_number=1,
            text="chunk text",
            token_count=2,
            metadata_json={},
        )
    )
    await session.flush()
    return document


async def _create_completed_run_with_results(
    session: AsyncSession, document_id: uuid.UUID
) -> ExtractionRun:
    run = ExtractionRun(
        document_id=document_id,
        pipeline_version="3.2.0",
        provider="groq",
        model="test-model",
        prompt_version="1.0",
        prompt_hash="hash",
        status=ExtractionStatus.COMPLETED,
        token_usage={},
    )
    session.add(run)
    await session.flush()

    entity = ExtractedEntity(
        extraction_run_id=run.id,
        entity_type=EntityType.COMMODITY,
        raw_value="Brent",
        confidence=0.9,
        provider="groq",
        model="test-model",
        prompt_version="1.0",
    )
    session.add(entity)

    table = ExtractedTable(
        extraction_run_id=run.id,
        page_number=1,
        confidence=0.9,
        row_count=1,
        column_count=1,
        metadata_json={},
    )
    session.add(table)
    await session.flush()
    session.add(TableCell(table_id=table.id, row=0, column=0, confidence=0.9))
    await session.flush()
    return run


class TestTriggerExtraction:
    async def test_requires_authentication(self, client: AsyncClient) -> None:
        response = await client.post(f"/api/v1/documents/{uuid.uuid4()}/extract")
        assert response.status_code == 401

    async def test_viewer_lacks_permission(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        token = await _register_and_login(client)
        response = await client.post(
            f"/api/v1/documents/{uuid.uuid4()}/extract",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 403

    async def test_analyst_triggers_extraction_run(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _register_and_login(client)
        await _promote(db_session, REGISTER_PAYLOAD["email"], "analyst")
        token = await _login(client)  # re-login: the access token embeds roles at issuance
        document = await _create_document_with_chunk(db_session)

        response = await client.post(
            f"/api/v1/documents/{document.id}/extract",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 202
        body = response.json()["data"]
        assert body["document_id"] == str(document.id)
        assert body["status"] == "pending"
        assert body["prompt_version"] == "1.0"

    async def test_missing_document_returns_404(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _register_and_login(client)
        await _promote(db_session, REGISTER_PAYLOAD["email"], "analyst")
        token = await _login(client)

        response = await client.post(
            f"/api/v1/documents/{uuid.uuid4()}/extract",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 404

    async def test_document_with_no_chunks_returns_409(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _register_and_login(client)
        await _promote(db_session, REGISTER_PAYLOAD["email"], "analyst")
        token = await _login(client)
        document = Document(
            filename="doc.pdf",
            original_filename="doc.pdf",
            extension=".pdf",
            mime_type="application/pdf",
            file_size=100,
            sha256_hash=uuid.uuid4().hex + "0" * 32,
            storage_provider=StorageProviderKind.LOCAL,
            storage_key="doc.pdf",
        )
        db_session.add(document)
        await db_session.flush()

        response = await client.post(
            f"/api/v1/documents/{document.id}/extract",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 409

    async def test_matching_fingerprint_returns_existing_completed_run(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Phase 3.3's extraction fingerprint: an identical extraction
        (same document content, prompts, pipeline version, provider,
        model) that already COMPLETED should be handed back as-is,
        without enqueueing a new run."""
        await _register_and_login(client)
        await _promote(db_session, REGISTER_PAYLOAD["email"], "analyst")
        token = await _login(client)
        document = await _create_document_with_chunk(db_session)

        settings = get_settings()
        provider, model = _resolve_provider_and_model(settings)
        prompt = get_extraction_prompt_registry().get("document_understanding")
        prompt_hash = get_extraction_prompt_registry().compute_hash(prompt)
        fingerprint = compute_extraction_fingerprint(
            document_hash=document.sha256_hash,
            prompt_hash=prompt_hash,
            pipeline_version="3.2.0",
            provider=provider,
            model=model,
        )
        existing_run = ExtractionRun(
            document_id=document.id,
            pipeline_version="3.2.0",
            provider=provider,
            model=model,
            prompt_version=str(prompt.version),
            prompt_hash=prompt_hash,
            extraction_fingerprint=fingerprint,
            status=ExtractionStatus.COMPLETED,
            token_usage={},
        )
        db_session.add(existing_run)
        await db_session.flush()

        response = await client.post(
            f"/api/v1/documents/{document.id}/extract",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 202
        assert response.json()["data"]["id"] == str(existing_run.id)

        stmt = select(ExtractionRun).where(ExtractionRun.document_id == document.id)
        all_runs = (await db_session.execute(stmt)).scalars().all()
        assert len(all_runs) == 1  # no new run was created

    async def test_different_document_content_creates_a_new_run(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _register_and_login(client)
        await _promote(db_session, REGISTER_PAYLOAD["email"], "analyst")
        token = await _login(client)
        document = await _create_document_with_chunk(db_session)

        settings = get_settings()
        provider, model = _resolve_provider_and_model(settings)
        prompt = get_extraction_prompt_registry().get("document_understanding")
        prompt_hash = get_extraction_prompt_registry().compute_hash(prompt)
        # A fingerprint computed against different document content -
        # deliberately does not match this document's real sha256_hash.
        unrelated_fingerprint = compute_extraction_fingerprint(
            document_hash="0" * 64,
            prompt_hash=prompt_hash,
            pipeline_version="3.2.0",
            provider=provider,
            model=model,
        )
        db_session.add(
            ExtractionRun(
                document_id=document.id,
                pipeline_version="3.2.0",
                provider=provider,
                model=model,
                prompt_version=str(prompt.version),
                prompt_hash=prompt_hash,
                extraction_fingerprint=unrelated_fingerprint,
                status=ExtractionStatus.COMPLETED,
                token_usage={},
            )
        )
        await db_session.flush()

        response = await client.post(
            f"/api/v1/documents/{document.id}/extract",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 202
        assert response.json()["data"]["status"] == "pending"

        stmt = select(ExtractionRun).where(ExtractionRun.document_id == document.id)
        all_runs = (await db_session.execute(stmt)).scalars().all()
        assert len(all_runs) == 2  # the unrelated completed run plus a new pending one


class TestGetExtractionRun:
    async def test_viewer_can_read_run_status(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        token = await _register_and_login(client)
        document = await _create_document_with_chunk(db_session)
        run = await _create_completed_run_with_results(db_session, document.id)

        response = await client.get(
            f"/api/v1/extraction-runs/{run.id}", headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        assert response.json()["data"]["status"] == "completed"

    async def test_missing_run_returns_404(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        token = await _register_and_login(client)
        response = await client.get(
            f"/api/v1/extraction-runs/{uuid.uuid4()}", headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 404


class TestListEntitiesAndTables:
    async def test_lists_entities_from_the_most_recent_run(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        token = await _register_and_login(client)
        document = await _create_document_with_chunk(db_session)
        await _create_completed_run_with_results(db_session, document.id)

        response = await client.get(
            f"/api/v1/documents/{document.id}/entities",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["meta"]["total_items"] == 1
        assert body["data"][0]["raw_value"] == "Brent"

    async def test_lists_tables_from_the_most_recent_run(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        token = await _register_and_login(client)
        document = await _create_document_with_chunk(db_session)
        await _create_completed_run_with_results(db_session, document.id)

        response = await client.get(
            f"/api/v1/documents/{document.id}/tables",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["meta"]["total_items"] == 1

    async def test_document_with_no_extraction_yet_returns_empty_list(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        token = await _register_and_login(client)
        document = await _create_document_with_chunk(db_session)

        response = await client.get(
            f"/api/v1/documents/{document.id}/entities",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        assert response.json()["data"] == []
        assert response.json()["meta"]["total_items"] == 0


class TestGetExtractionTable:
    async def test_returns_table_with_cells(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        token = await _register_and_login(client)
        document = await _create_document_with_chunk(db_session)
        run = await _create_completed_run_with_results(db_session, document.id)
        table = (
            await db_session.execute(
                select(ExtractedTable).where(ExtractedTable.extraction_run_id == run.id)
            )
        ).scalar_one()

        response = await client.get(
            f"/api/v1/extraction-tables/{table.id}", headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        body = response.json()["data"]
        assert len(body["cells"]) == 1

    async def test_missing_table_returns_404(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        token = await _register_and_login(client)
        response = await client.get(
            f"/api/v1/extraction-tables/{uuid.uuid4()}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 404
