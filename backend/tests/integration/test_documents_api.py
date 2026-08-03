"""End-to-end document ingestion API tests against the real app, database,
Redis, and (redirected-to-tmp_path) local storage. These don't run a real
ARQ worker - process_document is exercised directly in
test_worker_pipeline.py - so processing_status stays "queued" here; these
tests cover the upload/list/get/delete/reprocess/job-status API surface
and RBAC, not the background pipeline itself.
"""

import io
import uuid

import fitz
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import Role, User
from app.modules.documents.models import Document, ProcessingStatus

REGISTER_PAYLOAD = {
    "email": "uploader@example.com",
    "full_name": "Test Uploader",
    "password": "a-genuinely-strong-password",
}


def _pdf_bytes(text: str = "Test report body text.") -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 100), text)
    buffer = io.BytesIO()
    document.save(buffer)
    document.close()
    return buffer.getvalue()


async def _promote(session: AsyncSession, email: str, role_name: str) -> None:
    user = (await session.execute(select(User).where(User.email == email))).scalar_one()
    role = (await session.execute(select(Role).where(Role.name == role_name))).scalar_one()
    user.roles.append(role)
    await session.flush()


async def _login(client: AsyncClient, email: str = REGISTER_PAYLOAD["email"]) -> str:
    login_response = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": REGISTER_PAYLOAD["password"]}
    )
    token: str = login_response.json()["data"]["access_token"]
    return token


async def _register_and_login(client: AsyncClient, email: str = REGISTER_PAYLOAD["email"]) -> str:
    payload = {**REGISTER_PAYLOAD, "email": email}
    await client.post("/api/v1/auth/register", json=payload)
    return await _login(client, email)


class TestUpload:
    @pytest.mark.asyncio
    async def test_upload_requires_authentication(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("report.pdf", _pdf_bytes(), "application/pdf")},
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_viewer_can_upload_a_pdf(self, client: AsyncClient) -> None:
        token = await _register_and_login(client)

        response = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("report.pdf", _pdf_bytes(), "application/pdf")},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 201
        body = response.json()["data"]
        assert body["document"]["original_filename"] == "report.pdf"
        assert body["document"]["processing_status"] == "queued"
        assert body["document"]["upload_status"] == "pending"
        assert body["job"]["job_type"] == "ingestion"
        assert body["job"]["status"] == "queued"

    @pytest.mark.asyncio
    async def test_upload_rejects_disallowed_extension(self, client: AsyncClient) -> None:
        token = await _register_and_login(client)

        response = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("malware.exe", b"not a pdf", "application/pdf")},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 422
        assert response.json()["error_code"] == "invalid_upload"

    @pytest.mark.asyncio
    async def test_duplicate_upload_is_rejected(self, client: AsyncClient) -> None:
        token = await _register_and_login(client)
        pdf_bytes = _pdf_bytes("Identical content for duplicate detection.")

        first = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("report.pdf", pdf_bytes, "application/pdf")},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert first.status_code == 201

        second = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("report-copy.pdf", pdf_bytes, "application/pdf")},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert second.status_code == 409
        expected_id = first.json()["data"]["document"]["id"]
        assert second.json()["details"]["existing_document_id"] == expected_id


class TestListAndGet:
    @pytest.mark.asyncio
    async def test_list_documents_includes_uploaded_document(self, client: AsyncClient) -> None:
        token = await _register_and_login(client)
        upload = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("report.pdf", _pdf_bytes(), "application/pdf")},
            headers={"Authorization": f"Bearer {token}"},
        )
        document_id = upload.json()["data"]["document"]["id"]

        response = await client.get(
            "/api/v1/documents", headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 200
        ids = [d["id"] for d in response.json()["data"]]
        assert document_id in ids

    @pytest.mark.asyncio
    async def test_get_document_includes_download_url(self, client: AsyncClient) -> None:
        token = await _register_and_login(client)
        upload = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("report.pdf", _pdf_bytes(), "application/pdf")},
            headers={"Authorization": f"Bearer {token}"},
        )
        document_id = upload.json()["data"]["document"]["id"]

        response = await client.get(
            f"/api/v1/documents/{document_id}", headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 200
        body = response.json()["data"]
        assert body["download_url"].startswith("/api/v1/documents/files/")

    @pytest.mark.asyncio
    async def test_get_missing_document_returns_404(self, client: AsyncClient) -> None:
        token = await _register_and_login(client)
        response = await client.get(
            "/api/v1/documents/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 404


class TestDeleteAndReprocessPermissions:
    @pytest.mark.asyncio
    async def test_viewer_cannot_delete(self, client: AsyncClient) -> None:
        token = await _register_and_login(client)
        upload = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("report.pdf", _pdf_bytes(), "application/pdf")},
            headers={"Authorization": f"Bearer {token}"},
        )
        document_id = upload.json()["data"]["document"]["id"]

        response = await client.delete(
            f"/api/v1/documents/{document_id}", headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_viewer_cannot_reprocess(self, client: AsyncClient) -> None:
        token = await _register_and_login(client)
        upload = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("report.pdf", _pdf_bytes(), "application/pdf")},
            headers={"Authorization": f"Bearer {token}"},
        )
        document_id = upload.json()["data"]["document"]["id"]

        response = await client.post(
            f"/api/v1/documents/{document_id}/reprocess",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_analyst_can_delete_then_document_is_excluded_from_list(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        token = await _register_and_login(client)
        await _promote(db_session, REGISTER_PAYLOAD["email"], "analyst")
        # Re-login so the access token embeds the new permission set.
        token = await _login(client)
        upload = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("report.pdf", _pdf_bytes(), "application/pdf")},
            headers={"Authorization": f"Bearer {token}"},
        )
        document_id = upload.json()["data"]["document"]["id"]

        delete_response = await client.delete(
            f"/api/v1/documents/{document_id}", headers={"Authorization": f"Bearer {token}"}
        )
        assert delete_response.status_code == 204

        get_response = await client.get(
            f"/api/v1/documents/{document_id}", headers={"Authorization": f"Bearer {token}"}
        )
        assert get_response.status_code == 404

    @pytest.mark.asyncio
    async def test_analyst_can_reprocess(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        token = await _register_and_login(client)
        await _promote(db_session, REGISTER_PAYLOAD["email"], "analyst")
        token = await _login(client)
        upload = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("report.pdf", _pdf_bytes(), "application/pdf")},
            headers={"Authorization": f"Bearer {token}"},
        )
        document_id = upload.json()["data"]["document"]["id"]

        # No worker runs during this test, so the document is still
        # "queued" from the initial upload - reprocessing something
        # already in flight is correctly rejected (see the test below),
        # so simulate a finished document first.
        document = await db_session.get(Document, uuid.UUID(document_id))
        assert document is not None
        document.processing_status = ProcessingStatus.COMPLETED
        await db_session.flush()

        response = await client.post(
            f"/api/v1/documents/{document_id}/reprocess",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 202
        assert response.json()["data"]["job_type"] == "reprocess"

    @pytest.mark.asyncio
    async def test_reprocess_rejects_document_already_in_progress(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        token = await _register_and_login(client)
        await _promote(db_session, REGISTER_PAYLOAD["email"], "analyst")
        token = await _login(client)
        upload = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("report.pdf", _pdf_bytes(), "application/pdf")},
            headers={"Authorization": f"Bearer {token}"},
        )
        document_id = upload.json()["data"]["document"]["id"]

        response = await client.post(
            f"/api/v1/documents/{document_id}/reprocess",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 409


class TestProcessingJobStatus:
    @pytest.mark.asyncio
    async def test_get_job_status_after_upload(self, client: AsyncClient) -> None:
        token = await _register_and_login(client)
        upload = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("report.pdf", _pdf_bytes(), "application/pdf")},
            headers={"Authorization": f"Bearer {token}"},
        )
        job_id = upload.json()["data"]["job"]["id"]

        response = await client.get(
            f"/api/v1/processing-jobs/{job_id}", headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 200
        assert response.json()["data"]["status"] == "queued"

    @pytest.mark.asyncio
    async def test_get_missing_job_returns_404(self, client: AsyncClient) -> None:
        token = await _register_and_login(client)
        response = await client.get(
            "/api/v1/processing-jobs/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 404
