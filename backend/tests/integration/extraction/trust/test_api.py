"""End-to-end trust-pipeline API tests against the real app, database, and
Redis. No real worker runs here - trigger_validation enqueues a real ARQ
job that nothing consumes in-process, same pattern
tests/integration/extraction/test_api.py uses for trigger_extraction;
these cover the API/RBAC surface, not the pipeline itself (see
test_worker_pipeline.py for that).
"""

import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.extraction.models import ExtractionRun, ExtractionStatus
from app.modules.extraction.trust.models import (
    ConfidenceScore,
    NormalizationResult,
    ReviewPriority,
    ReviewQueueItem,
    ReviewStatus,
    TrustPipelineRun,
    ValidationCategory,
    ValidationResult,
    ValidationSeverity,
)
from tests.integration.extraction.test_api import (
    REGISTER_PAYLOAD,
    _create_completed_run_with_results,
    _create_document_with_chunk,
    _login,
    _promote,
    _register_and_login,
)


async def _entity_id_from_run(session: AsyncSession, run: ExtractionRun) -> uuid.UUID:
    from sqlalchemy import select

    from app.modules.extraction.models import ExtractedEntity

    entity = (
        await session.execute(
            select(ExtractedEntity).where(ExtractedEntity.extraction_run_id == run.id)
        )
    ).scalar_one()
    return entity.id


class TestTriggerValidation:
    async def test_requires_authentication(self, client: AsyncClient) -> None:
        response = await client.post(f"/api/v1/extraction-runs/{uuid.uuid4()}/validate")
        assert response.status_code == 401

    async def test_viewer_lacks_permission(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        token = await _register_and_login(client)
        response = await client.post(
            f"/api/v1/extraction-runs/{uuid.uuid4()}/validate",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 403

    async def test_analyst_triggers_trust_run(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _register_and_login(client)
        await _promote(db_session, REGISTER_PAYLOAD["email"], "analyst")
        token = await _login(client)
        document = await _create_document_with_chunk(db_session)
        run = await _create_completed_run_with_results(db_session, document.id)

        response = await client.post(
            f"/api/v1/extraction-runs/{run.id}/validate",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 202
        body = response.json()["data"]
        assert body["extraction_run_id"] == str(run.id)
        assert body["status"] == "pending"

    async def test_missing_extraction_run_returns_404(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _register_and_login(client)
        await _promote(db_session, REGISTER_PAYLOAD["email"], "analyst")
        token = await _login(client)

        response = await client.post(
            f"/api/v1/extraction-runs/{uuid.uuid4()}/validate",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 404

    async def test_extraction_still_running_returns_409(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _register_and_login(client)
        await _promote(db_session, REGISTER_PAYLOAD["email"], "analyst")
        token = await _login(client)
        document = await _create_document_with_chunk(db_session)
        run = ExtractionRun(
            document_id=document.id,
            pipeline_version="3.2.0",
            provider="groq",
            model="test-model",
            prompt_version="1.0",
            prompt_hash="hash",
            status=ExtractionStatus.RUNNING,
            token_usage={},
        )
        db_session.add(run)
        await db_session.flush()

        response = await client.post(
            f"/api/v1/extraction-runs/{run.id}/validate",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 409


class TestReadTrustResults:
    async def test_viewer_can_list_trust_runs(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        token = await _register_and_login(client)
        document = await _create_document_with_chunk(db_session)
        run = await _create_completed_run_with_results(db_session, document.id)
        trust_run = TrustPipelineRun(
            extraction_run_id=run.id,
            pipeline_version="3.3.0",
            rule_registry_version="1.0",
            status=ExtractionStatus.COMPLETED,
        )
        db_session.add(trust_run)
        await db_session.flush()

        response = await client.get(
            f"/api/v1/extraction-runs/{run.id}/trust-runs",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        assert len(response.json()["data"]) == 1

    async def test_get_single_trust_run(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        token = await _register_and_login(client)
        document = await _create_document_with_chunk(db_session)
        run = await _create_completed_run_with_results(db_session, document.id)
        trust_run = TrustPipelineRun(
            extraction_run_id=run.id,
            pipeline_version="3.3.0",
            rule_registry_version="1.0",
            status=ExtractionStatus.COMPLETED,
        )
        db_session.add(trust_run)
        await db_session.flush()

        response = await client.get(
            f"/api/v1/trust-runs/{trust_run.id}", headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        assert response.json()["data"]["status"] == "completed"

    async def test_missing_trust_run_returns_404(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        token = await _register_and_login(client)
        response = await client.get(
            f"/api/v1/trust-runs/{uuid.uuid4()}", headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 404

    async def test_lists_validation_results_for_a_run(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        token = await _register_and_login(client)
        document = await _create_document_with_chunk(db_session)
        run = await _create_completed_run_with_results(db_session, document.id)
        entity_id = await _entity_id_from_run(db_session, run)
        db_session.add(
            ValidationResult(
                extraction_run_id=run.id,
                entity_id=entity_id,
                validation_rule="currency.invalid_code",
                validation_type=ValidationCategory.CURRENCY,
                severity=ValidationSeverity.ERROR,
                passed=False,
                message="bad currency",
            )
        )
        await db_session.flush()

        response = await client.get(
            f"/api/v1/extraction-runs/{run.id}/validation-results",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["meta"]["total_items"] == 1
        assert body["data"][0]["passed"] is False

    async def test_get_entity_confidence(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        token = await _register_and_login(client)
        document = await _create_document_with_chunk(db_session)
        run = await _create_completed_run_with_results(db_session, document.id)
        entity_id = await _entity_id_from_run(db_session, run)
        db_session.add(
            ConfidenceScore(
                entity_id=entity_id,
                overall_score=0.8,
                extraction_score=0.9,
                geometry_score=1.0,
                layout_score=1.0,
                table_score=1.0,
                consistency_score=1.0,
                normalization_score=1.0,
                validation_score=1.0,
                provider_score=0.85,
                explanation_json={},
            )
        )
        await db_session.flush()

        response = await client.get(
            f"/api/v1/extracted-entities/{entity_id}/confidence",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        assert response.json()["data"]["overall_score"] == 0.8

    async def test_get_entity_confidence_missing_returns_404(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        token = await _register_and_login(client)
        response = await client.get(
            f"/api/v1/extracted-entities/{uuid.uuid4()}/confidence",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 404

    async def test_get_entity_normalization(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        token = await _register_and_login(client)
        document = await _create_document_with_chunk(db_session)
        run = await _create_completed_run_with_results(db_session, document.id)
        entity_id = await _entity_id_from_run(db_session, run)
        db_session.add(
            NormalizationResult(
                entity_id=entity_id,
                canonical_id="commodity:brent_crude",
                canonical_name="Brent Crude",
                normalized_value="Brent Crude",
                normalization_method="alias_lookup",
                confidence=1.0,
            )
        )
        await db_session.flush()

        response = await client.get(
            f"/api/v1/extracted-entities/{entity_id}/normalization",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        assert response.json()["data"]["canonical_id"] == "commodity:brent_crude"


class TestReviewQueue:
    async def test_list_review_queue(self, client: AsyncClient, db_session: AsyncSession) -> None:
        token = await _register_and_login(client)
        document = await _create_document_with_chunk(db_session)
        run = await _create_completed_run_with_results(db_session, document.id)
        entity_id = await _entity_id_from_run(db_session, run)
        db_session.add(
            ReviewQueueItem(
                extraction_run_id=run.id,
                entity_id=entity_id,
                reason="low confidence",
                priority=ReviewPriority.MEDIUM,
            )
        )
        await db_session.flush()

        response = await client.get(
            "/api/v1/review-queue", headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        assert response.json()["meta"]["total_items"] == 1

    async def test_list_review_queue_filters_by_status(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        token = await _register_and_login(client)
        document = await _create_document_with_chunk(db_session)
        run = await _create_completed_run_with_results(db_session, document.id)
        entity_id = await _entity_id_from_run(db_session, run)
        db_session.add(
            ReviewQueueItem(
                extraction_run_id=run.id,
                entity_id=entity_id,
                reason="low confidence",
                priority=ReviewPriority.MEDIUM,
                status=ReviewStatus.RESOLVED,
            )
        )
        await db_session.flush()

        response = await client.get(
            "/api/v1/review-queue?status=pending",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        assert response.json()["meta"]["total_items"] == 0

    async def test_viewer_cannot_update_review_item(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        token = await _register_and_login(client)
        document = await _create_document_with_chunk(db_session)
        run = await _create_completed_run_with_results(db_session, document.id)
        entity_id = await _entity_id_from_run(db_session, run)
        item = ReviewQueueItem(
            extraction_run_id=run.id,
            entity_id=entity_id,
            reason="low confidence",
            priority=ReviewPriority.MEDIUM,
        )
        db_session.add(item)
        await db_session.flush()

        response = await client.patch(
            f"/api/v1/review-queue/{item.id}",
            json={"status": "resolved"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 403

    async def test_analyst_resolves_a_review_item(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _register_and_login(client)
        await _promote(db_session, REGISTER_PAYLOAD["email"], "analyst")
        token = await _login(client)
        document = await _create_document_with_chunk(db_session)
        run = await _create_completed_run_with_results(db_session, document.id)
        entity_id = await _entity_id_from_run(db_session, run)
        item = ReviewQueueItem(
            extraction_run_id=run.id,
            entity_id=entity_id,
            reason="low confidence",
            priority=ReviewPriority.MEDIUM,
        )
        db_session.add(item)
        await db_session.flush()

        response = await client.patch(
            f"/api/v1/review-queue/{item.id}",
            json={"status": "resolved", "resolution": "confirmed correct"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        body = response.json()["data"]
        assert body["status"] == "resolved"
        assert body["resolution"] == "confirmed correct"
        assert body["reviewed_at"] is not None

    async def test_missing_review_item_returns_404(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        token = await _register_and_login(client)
        response = await client.get(
            f"/api/v1/review-queue/{uuid.uuid4()}", headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 404
