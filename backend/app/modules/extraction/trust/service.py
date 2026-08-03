"""TrustPipelineService: trigger a new validation/confidence/normalization
run for an already-completed extraction run (its own lifecycle, separate
from extraction itself - see docs/ARCHITECTURE.md), read its results, and
manage the human review queue.
"""

import uuid
from datetime import UTC, datetime

from app.core.exceptions import ConflictError, NotFoundError
from app.modules.audit.service import AuditService
from app.modules.extraction.models import ExtractionStatus
from app.modules.extraction.queue import JobQueue
from app.modules.extraction.repository import ExtractionRunRepository
from app.modules.extraction.trust.models import (
    ConfidenceScore,
    NormalizationResult,
    ReviewQueueItem,
    ReviewStatus,
    TrustPipelineRun,
    ValidationResult,
)
from app.modules.extraction.trust.repository import (
    ConfidenceScoreRepository,
    NormalizationResultRepository,
    ReviewQueueRepository,
    TrustPipelineRunRepository,
    ValidationResultRepository,
)
from app.modules.extraction.trust.rules.builtin import RULE_REGISTRY_VERSION

PIPELINE_VERSION = "3.3.0"

_ACTIVE_STATUSES = (ExtractionStatus.PENDING, ExtractionStatus.RUNNING)


class TrustPipelineService:
    def __init__(
        self,
        *,
        extraction_run_repo: ExtractionRunRepository,
        trust_run_repo: TrustPipelineRunRepository,
        validation_repo: ValidationResultRepository,
        confidence_repo: ConfidenceScoreRepository,
        normalization_repo: NormalizationResultRepository,
        review_queue_repo: ReviewQueueRepository,
        audit_service: AuditService,
        job_queue: JobQueue,
    ) -> None:
        self.extraction_run_repo = extraction_run_repo
        self.trust_run_repo = trust_run_repo
        self.validation_repo = validation_repo
        self.confidence_repo = confidence_repo
        self.normalization_repo = normalization_repo
        self.review_queue_repo = review_queue_repo
        self.audit_service = audit_service
        self.job_queue = job_queue

    async def trigger_validation(
        self, extraction_run_id: uuid.UUID, *, requested_by: uuid.UUID
    ) -> TrustPipelineRun:
        extraction_run = await self.extraction_run_repo.get_by_id(extraction_run_id)
        if extraction_run is None:
            raise NotFoundError(f"Extraction run {extraction_run_id} not found")
        if extraction_run.status != ExtractionStatus.COMPLETED:
            raise ConflictError(
                "Extraction must be COMPLETED before it can be validated "
                f"(current status: {extraction_run.status.value})"
            )

        latest = await self.trust_run_repo.latest_for_extraction_run(extraction_run_id)
        if latest is not None and latest.status in _ACTIVE_STATUSES:
            raise ConflictError(
                "A trust pipeline run is already in progress for this extraction run"
            )

        run = await self.trust_run_repo.create(
            TrustPipelineRun(
                extraction_run_id=extraction_run_id,
                pipeline_version=PIPELINE_VERSION,
                rule_registry_version=RULE_REGISTRY_VERSION,
                status=ExtractionStatus.PENDING,
            )
        )
        await self.audit_service.record(
            user_id=requested_by,
            action="extraction_run.validation_requested",
            resource_type="extraction_run",
            resource_id=extraction_run_id,
            metadata={"trust_pipeline_run_id": str(run.id)},
        )
        await self.job_queue.enqueue_job("run_trust_pipeline", str(extraction_run_id), str(run.id))
        return run

    async def get_trust_run(self, trust_run_id: uuid.UUID) -> TrustPipelineRun:
        run = await self.trust_run_repo.get_by_id(trust_run_id)
        if run is None:
            raise NotFoundError(f"Trust pipeline run {trust_run_id} not found")
        return run

    async def list_trust_runs(self, extraction_run_id: uuid.UUID) -> list[TrustPipelineRun]:
        return await self.trust_run_repo.list_for_extraction_run(extraction_run_id)

    async def list_validation_results(
        self, extraction_run_id: uuid.UUID, *, offset: int = 0, limit: int = 100
    ) -> tuple[list[ValidationResult], int]:
        results = await self.validation_repo.list_for_run(
            extraction_run_id, offset=offset, limit=limit
        )
        total = await self.validation_repo.count_for_run(extraction_run_id)
        return results, total

    async def get_confidence(self, entity_id: uuid.UUID) -> ConfidenceScore:
        score = await self.confidence_repo.get_by_id(entity_id)
        if score is None:
            raise NotFoundError(f"No confidence score for entity {entity_id}")
        return score

    async def get_normalization(self, entity_id: uuid.UUID) -> NormalizationResult:
        result = await self.normalization_repo.get_by_id(entity_id)
        if result is None:
            raise NotFoundError(f"No normalization result for entity {entity_id}")
        return result

    async def list_review_queue(
        self, *, status: ReviewStatus | None = None, offset: int = 0, limit: int = 100
    ) -> tuple[list[ReviewQueueItem], int]:
        items = await self.review_queue_repo.list_queue(status=status, offset=offset, limit=limit)
        total = await self.review_queue_repo.count_queue(status=status)
        return items, total

    async def get_review_item(self, review_item_id: uuid.UUID) -> ReviewQueueItem:
        item = await self.review_queue_repo.get_by_id(review_item_id)
        if item is None:
            raise NotFoundError(f"Review queue item {review_item_id} not found")
        return item

    async def update_review_item(
        self,
        review_item_id: uuid.UUID,
        *,
        status: ReviewStatus | None,
        assigned_to: uuid.UUID | None,
        resolution: str | None,
        requested_by: uuid.UUID,
    ) -> ReviewQueueItem:
        item = await self.get_review_item(review_item_id)
        fields: dict[str, object] = {}
        if status is not None:
            fields["status"] = status
            if status in (ReviewStatus.RESOLVED, ReviewStatus.DISMISSED):
                fields["reviewed_at"] = datetime.now(UTC)
        if assigned_to is not None:
            fields["assigned_to"] = assigned_to
        if resolution is not None:
            fields["resolution"] = resolution

        updated = await self.review_queue_repo.update(item, **fields)
        await self.audit_service.record(
            user_id=requested_by,
            action="review_queue.updated",
            resource_type="review_queue_item",
            resource_id=review_item_id,
            metadata={"status": updated.status.value},
        )
        return updated
