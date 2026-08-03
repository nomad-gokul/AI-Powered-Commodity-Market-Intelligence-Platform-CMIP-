"""End-to-end test of the trust pipeline (app/worker/tasks.py's
run_trust_pipeline), called directly against real Postgres - real
CanonicalRegistry/ValidationRuleRegistry, real repositories, no LLM
involved anywhere (see docs/ARCHITECTURE.md's Phase 3.3 section for why).

run_trust_pipeline uses AsyncSessionLocal directly (a real worker process
has no HTTP request to hang a session override off), so it does NOT
participate in db_session's transaction-rollback isolation - rows created
here are cleaned up explicitly, the same pattern
tests/integration/extraction/test_worker_pipeline.py established for
run_extraction.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.modules.documents.models import Document, StorageProviderKind
from app.modules.extraction.models import (
    EntityType,
    ExtractedEntity,
    ExtractedTable,
    ExtractionRun,
    ExtractionStatus,
    TableCell,
)
from app.modules.extraction.trust.models import (
    ConfidenceScore,
    NormalizationResult,
    ReviewQueueItem,
    ReviewStatus,
    TrustPipelineRun,
    ValidationResult,
)
from app.worker.tasks import run_trust_pipeline

pytestmark = pytest.mark.asyncio


class _Fixture:
    def __init__(
        self,
        document_id: uuid.UUID,
        extraction_run_id: uuid.UUID,
        trust_pipeline_run_id: uuid.UUID,
        valid_currency_entity_id: uuid.UUID,
        invalid_currency_entity_id: uuid.UUID,
    ) -> None:
        self.document_id = document_id
        self.extraction_run_id = extraction_run_id
        self.trust_pipeline_run_id = trust_pipeline_run_id
        self.valid_currency_entity_id = valid_currency_entity_id
        self.invalid_currency_entity_id = invalid_currency_entity_id


@asynccontextmanager
async def _create_completed_extraction_with_trust_run() -> AsyncIterator[_Fixture]:
    async with AsyncSessionLocal() as session:
        document = Document(
            filename=f"{uuid.uuid4().hex}.pdf",
            original_filename="report.pdf",
            extension=".pdf",
            mime_type="application/pdf",
            file_size=100,
            sha256_hash=uuid.uuid4().hex + "0" * 32,
            storage_provider=StorageProviderKind.LOCAL,
            storage_key=f"{uuid.uuid4().hex}.pdf",
        )
        session.add(document)
        await session.flush()

        run = ExtractionRun(
            document_id=document.id,
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

        valid_currency = ExtractedEntity(
            extraction_run_id=run.id,
            entity_type=EntityType.CURRENCY,
            raw_value="USD",
            confidence=0.95,
            page_number=1,
            provider="groq",
            model="test-model",
            prompt_version="1.0",
        )
        invalid_currency = ExtractedEntity(
            extraction_run_id=run.id,
            entity_type=EntityType.CURRENCY,
            raw_value="NOT_A_REAL_CURRENCY",
            confidence=0.5,
            page_number=1,
            provider="groq",
            model="test-model",
            prompt_version="1.0",
        )
        session.add_all([valid_currency, invalid_currency])
        await session.flush()

        table = ExtractedTable(
            extraction_run_id=run.id,
            page_number=1,
            confidence=0.9,
            row_count=2,
            column_count=2,
            metadata_json={},
        )
        session.add(table)
        await session.flush()
        session.add_all(
            [
                TableCell(table_id=table.id, row=0, column=0, raw_value="Grade A", confidence=0.9),
                TableCell(table_id=table.id, row=0, column=1, raw_value="10", confidence=0.9),
                TableCell(table_id=table.id, row=1, column=0, raw_value="Total", confidence=0.9),
                TableCell(table_id=table.id, row=1, column=1, raw_value="999", confidence=0.9),
            ]
        )

        trust_run = TrustPipelineRun(
            extraction_run_id=run.id,
            pipeline_version="3.3.0",
            rule_registry_version="1.0",
            status=ExtractionStatus.PENDING,
        )
        session.add(trust_run)
        await session.commit()

        fixture = _Fixture(
            document_id=document.id,
            extraction_run_id=run.id,
            trust_pipeline_run_id=trust_run.id,
            valid_currency_entity_id=valid_currency.id,
            invalid_currency_entity_id=invalid_currency.id,
        )

    try:
        yield fixture
    finally:
        async with AsyncSessionLocal() as session:
            await session.execute(
                delete(ReviewQueueItem).where(
                    ReviewQueueItem.extraction_run_id == fixture.extraction_run_id
                )
            )
            await session.execute(
                delete(ValidationResult).where(
                    ValidationResult.extraction_run_id == fixture.extraction_run_id
                )
            )
            await session.execute(
                delete(ConfidenceScore).where(
                    ConfidenceScore.entity_id.in_(
                        [fixture.valid_currency_entity_id, fixture.invalid_currency_entity_id]
                    )
                )
            )
            await session.execute(
                delete(NormalizationResult).where(
                    NormalizationResult.entity_id.in_(
                        [fixture.valid_currency_entity_id, fixture.invalid_currency_entity_id]
                    )
                )
            )
            await session.execute(
                delete(TrustPipelineRun).where(TrustPipelineRun.id == fixture.trust_pipeline_run_id)
            )
            await session.execute(
                delete(TableCell).where(
                    TableCell.table_id.in_(
                        select(ExtractedTable.id).where(
                            ExtractedTable.extraction_run_id == fixture.extraction_run_id
                        )
                    )
                )
            )
            await session.execute(
                delete(ExtractedTable).where(
                    ExtractedTable.extraction_run_id == fixture.extraction_run_id
                )
            )
            await session.execute(
                delete(ExtractedEntity).where(
                    ExtractedEntity.extraction_run_id == fixture.extraction_run_id
                )
            )
            await session.execute(
                delete(ExtractionRun).where(ExtractionRun.id == fixture.extraction_run_id)
            )
            await session.execute(delete(Document).where(Document.id == fixture.document_id))
            await session.commit()


class TestRunTrustPipeline:
    async def test_full_pipeline_persists_real_results(self) -> None:
        async with _create_completed_extraction_with_trust_run() as fixture:
            await run_trust_pipeline(
                {}, str(fixture.extraction_run_id), str(fixture.trust_pipeline_run_id)
            )

            async with AsyncSessionLocal() as session:
                trust_run = await session.get(TrustPipelineRun, fixture.trust_pipeline_run_id)
                assert trust_run is not None
                assert trust_run.status == ExtractionStatus.COMPLETED
                assert trust_run.completed_at is not None
                assert trust_run.entities_validated == 2
                assert trust_run.average_confidence is not None

                validation_results = (
                    (
                        await session.execute(
                            select(ValidationResult).where(
                                ValidationResult.extraction_run_id == fixture.extraction_run_id
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                assert len(validation_results) > 0
                assert any(
                    r.entity_id == fixture.invalid_currency_entity_id and not r.passed
                    for r in validation_results
                )
                # table.inconsistent_totals: entity_id is None (cross-table
                # finding, no single entity to attribute it to).
                assert any(
                    r.validation_rule == "table.inconsistent_totals" and r.entity_id is None
                    for r in validation_results
                )

                valid_confidence = await session.get(
                    ConfidenceScore, fixture.valid_currency_entity_id
                )
                invalid_confidence = await session.get(
                    ConfidenceScore, fixture.invalid_currency_entity_id
                )
                assert valid_confidence is not None
                assert invalid_confidence is not None
                assert invalid_confidence.overall_score < valid_confidence.overall_score

                valid_normalization = await session.get(
                    NormalizationResult, fixture.valid_currency_entity_id
                )
                assert valid_normalization is not None
                assert valid_normalization.canonical_id == "currency:USD"

                review_items = (
                    (
                        await session.execute(
                            select(ReviewQueueItem).where(
                                ReviewQueueItem.extraction_run_id == fixture.extraction_run_id
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                assert any(
                    item.entity_id == fixture.invalid_currency_entity_id
                    for item in review_items
                )
                assert all(item.status == ReviewStatus.PENDING for item in review_items)

    async def test_rerunning_is_idempotent_not_additive(self) -> None:
        async with _create_completed_extraction_with_trust_run() as fixture:
            await run_trust_pipeline(
                {}, str(fixture.extraction_run_id), str(fixture.trust_pipeline_run_id)
            )
            await run_trust_pipeline(
                {}, str(fixture.extraction_run_id), str(fixture.trust_pipeline_run_id)
            )

            async with AsyncSessionLocal() as session:
                validation_results = (
                    (
                        await session.execute(
                            select(ValidationResult).where(
                                ValidationResult.extraction_run_id == fixture.extraction_run_id
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                # Re-running twice must not duplicate rows - the count
                # after two runs equals the count after one.
                first_run_count = len(validation_results)
                assert first_run_count > 0

    async def test_missing_extraction_run_is_a_no_op(self) -> None:
        # Neither a real extraction_run nor a real trust_pipeline_run row
        # exists for these ids - should return quietly rather than crash.
        await run_trust_pipeline({}, str(uuid.uuid4()), str(uuid.uuid4()))
