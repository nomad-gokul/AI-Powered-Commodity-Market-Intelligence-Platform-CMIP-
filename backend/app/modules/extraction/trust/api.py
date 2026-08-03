"""HTTP routes for triggering the trust pipeline and reading its results:
validation, confidence, normalization, and the human review queue. A
separate lifecycle from extraction itself - see docs/ARCHITECTURE.md.

Reuses extraction's own RBAC permissions (extraction:trigger,
extraction:read) rather than adding new ones: no new actor was
introduced this phase, so no new permission rows are warranted.
"""

import math
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.schemas import ApiResponse, PageMeta, PaginatedResponse
from app.core.database import get_db_session
from app.modules.audit.repository import AuditLogRepository
from app.modules.audit.service import AuditService
from app.modules.auth.dependencies import get_current_user, require_permission
from app.modules.auth.models import User
from app.modules.extraction.queue import JobQueue
from app.modules.extraction.repository import ExtractionRunRepository
from app.modules.extraction.trust.models import ReviewStatus
from app.modules.extraction.trust.repository import (
    ConfidenceScoreRepository,
    NormalizationResultRepository,
    ReviewQueueRepository,
    TrustPipelineRunRepository,
    ValidationResultRepository,
)
from app.modules.extraction.trust.schemas import (
    ConfidenceScoreRead,
    NormalizationResultRead,
    ReviewQueueItemRead,
    ReviewQueueUpdateRequest,
    TrustPipelineRunRead,
    ValidationResultRead,
)
from app.modules.extraction.trust.service import TrustPipelineService

runs_router = APIRouter(prefix="/extraction-runs", tags=["Trust"])
trust_runs_router = APIRouter(prefix="/trust-runs", tags=["Trust"])
entities_router = APIRouter(prefix="/extracted-entities", tags=["Trust"])
review_queue_router = APIRouter(prefix="/review-queue", tags=["Trust"])


def get_trust_pipeline_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    request: Request,
) -> TrustPipelineService:
    job_queue: JobQueue = request.app.state.arq_pool
    return TrustPipelineService(
        extraction_run_repo=ExtractionRunRepository(session),
        trust_run_repo=TrustPipelineRunRepository(session),
        validation_repo=ValidationResultRepository(session),
        confidence_repo=ConfidenceScoreRepository(session),
        normalization_repo=NormalizationResultRepository(session),
        review_queue_repo=ReviewQueueRepository(session),
        audit_service=AuditService(AuditLogRepository(session)),
        job_queue=job_queue,
    )


@runs_router.post(
    "/{extraction_run_id}/validate",
    response_model=ApiResponse[TrustPipelineRunRead],
    status_code=202,
    dependencies=[Depends(require_permission("extraction:trigger"))],
)
async def trigger_validation(
    extraction_run_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[TrustPipelineService, Depends(get_trust_pipeline_service)],
) -> ApiResponse[TrustPipelineRunRead]:
    run = await service.trigger_validation(extraction_run_id, requested_by=current_user.id)
    return ApiResponse(data=TrustPipelineRunRead.model_validate(run))


@runs_router.get(
    "/{extraction_run_id}/trust-runs",
    response_model=ApiResponse[list[TrustPipelineRunRead]],
    dependencies=[Depends(require_permission("extraction:read"))],
)
async def list_trust_runs(
    extraction_run_id: uuid.UUID,
    service: Annotated[TrustPipelineService, Depends(get_trust_pipeline_service)],
) -> ApiResponse[list[TrustPipelineRunRead]]:
    runs = await service.list_trust_runs(extraction_run_id)
    return ApiResponse(data=[TrustPipelineRunRead.model_validate(r) for r in runs])


@runs_router.get(
    "/{extraction_run_id}/validation-results",
    response_model=PaginatedResponse[ValidationResultRead],
    dependencies=[Depends(require_permission("extraction:read"))],
)
async def list_validation_results(
    extraction_run_id: uuid.UUID,
    service: Annotated[TrustPipelineService, Depends(get_trust_pipeline_service)],
    page: int = 1,
    page_size: int = 50,
) -> PaginatedResponse[ValidationResultRead]:
    results, total = await service.list_validation_results(
        extraction_run_id, offset=(page - 1) * page_size, limit=page_size
    )
    return PaginatedResponse(
        data=[ValidationResultRead.model_validate(r) for r in results],
        meta=PageMeta(
            page=page,
            page_size=page_size,
            total_items=total,
            total_pages=max(1, math.ceil(total / page_size)),
        ),
    )


@trust_runs_router.get(
    "/{trust_pipeline_run_id}",
    response_model=ApiResponse[TrustPipelineRunRead],
    dependencies=[Depends(require_permission("extraction:read"))],
)
async def get_trust_run(
    trust_pipeline_run_id: uuid.UUID,
    service: Annotated[TrustPipelineService, Depends(get_trust_pipeline_service)],
) -> ApiResponse[TrustPipelineRunRead]:
    run = await service.get_trust_run(trust_pipeline_run_id)
    return ApiResponse(data=TrustPipelineRunRead.model_validate(run))


@entities_router.get(
    "/{entity_id}/confidence",
    response_model=ApiResponse[ConfidenceScoreRead],
    dependencies=[Depends(require_permission("extraction:read"))],
)
async def get_entity_confidence(
    entity_id: uuid.UUID,
    service: Annotated[TrustPipelineService, Depends(get_trust_pipeline_service)],
) -> ApiResponse[ConfidenceScoreRead]:
    score = await service.get_confidence(entity_id)
    return ApiResponse(data=ConfidenceScoreRead.model_validate(score))


@entities_router.get(
    "/{entity_id}/normalization",
    response_model=ApiResponse[NormalizationResultRead],
    dependencies=[Depends(require_permission("extraction:read"))],
)
async def get_entity_normalization(
    entity_id: uuid.UUID,
    service: Annotated[TrustPipelineService, Depends(get_trust_pipeline_service)],
) -> ApiResponse[NormalizationResultRead]:
    result = await service.get_normalization(entity_id)
    return ApiResponse(data=NormalizationResultRead.model_validate(result))


@review_queue_router.get(
    "",
    response_model=PaginatedResponse[ReviewQueueItemRead],
    dependencies=[Depends(require_permission("extraction:read"))],
)
async def list_review_queue(
    service: Annotated[TrustPipelineService, Depends(get_trust_pipeline_service)],
    status: ReviewStatus | None = None,
    page: int = 1,
    page_size: int = 50,
) -> PaginatedResponse[ReviewQueueItemRead]:
    items, total = await service.list_review_queue(
        status=status, offset=(page - 1) * page_size, limit=page_size
    )
    return PaginatedResponse(
        data=[ReviewQueueItemRead.model_validate(i) for i in items],
        meta=PageMeta(
            page=page,
            page_size=page_size,
            total_items=total,
            total_pages=max(1, math.ceil(total / page_size)),
        ),
    )


@review_queue_router.get(
    "/{review_item_id}",
    response_model=ApiResponse[ReviewQueueItemRead],
    dependencies=[Depends(require_permission("extraction:read"))],
)
async def get_review_item(
    review_item_id: uuid.UUID,
    service: Annotated[TrustPipelineService, Depends(get_trust_pipeline_service)],
) -> ApiResponse[ReviewQueueItemRead]:
    item = await service.get_review_item(review_item_id)
    return ApiResponse(data=ReviewQueueItemRead.model_validate(item))


@review_queue_router.patch(
    "/{review_item_id}",
    response_model=ApiResponse[ReviewQueueItemRead],
    dependencies=[Depends(require_permission("extraction:trigger"))],
)
async def update_review_item(
    review_item_id: uuid.UUID,
    body: ReviewQueueUpdateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[TrustPipelineService, Depends(get_trust_pipeline_service)],
) -> ApiResponse[ReviewQueueItemRead]:
    item = await service.update_review_item(
        review_item_id,
        status=body.status,
        assigned_to=body.assigned_to,
        resolution=body.resolution,
        requested_by=current_user.id,
    )
    return ApiResponse(data=ReviewQueueItemRead.model_validate(item))
