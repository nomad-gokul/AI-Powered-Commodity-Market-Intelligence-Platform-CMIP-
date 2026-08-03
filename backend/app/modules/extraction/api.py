"""HTTP routes for triggering semantic extraction and reading its
results. A separate lifecycle from document ingestion - see
docs/ARCHITECTURE.md."""

import math
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.schemas import ApiResponse, PageMeta, PaginatedResponse
from app.core.config import Settings, get_settings
from app.core.database import get_db_session
from app.modules.audit.repository import AuditLogRepository
from app.modules.audit.service import AuditService
from app.modules.auth.dependencies import get_current_user, require_permission
from app.modules.auth.models import User
from app.modules.documents.repository import DocumentChunkRepository, DocumentRepository
from app.modules.extraction.prompts import get_extraction_prompt_registry
from app.modules.extraction.queue import JobQueue
from app.modules.extraction.repository import (
    ExtractedEntityRepository,
    ExtractedTableRepository,
    ExtractionRunRepository,
    TableCellRepository,
)
from app.modules.extraction.schemas import (
    ExtractedEntityRead,
    ExtractedTableDetailRead,
    ExtractedTableRead,
    ExtractionRunRead,
    TableCellRead,
)
from app.modules.extraction.service import ExtractionService

router = APIRouter(prefix="/documents", tags=["Extraction"])
runs_router = APIRouter(prefix="/extraction-runs", tags=["Extraction"])
tables_router = APIRouter(prefix="/extraction-tables", tags=["Extraction"])


def _resolve_provider_and_model(settings: Settings) -> tuple[str, str]:
    model_by_provider = {
        "groq": settings.groq_model,
        "claude": settings.claude_model,
        "openai": settings.openai_model,
        "ollama": settings.ollama_model,
    }
    return settings.llm_provider, model_by_provider[settings.llm_provider]


def get_extraction_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    request: Request,
) -> ExtractionService:
    settings = get_settings()
    provider, model = _resolve_provider_and_model(settings)
    job_queue: JobQueue = request.app.state.arq_pool
    return ExtractionService(
        document_repo=DocumentRepository(session),
        chunk_repo=DocumentChunkRepository(session),
        run_repo=ExtractionRunRepository(session),
        entity_repo=ExtractedEntityRepository(session),
        table_repo=ExtractedTableRepository(session),
        cell_repo=TableCellRepository(session),
        audit_service=AuditService(AuditLogRepository(session)),
        job_queue=job_queue,
        prompt_registry=get_extraction_prompt_registry(),
        provider=provider,
        model=model,
    )


@router.post(
    "/{document_id}/extract",
    response_model=ApiResponse[ExtractionRunRead],
    status_code=202,
    dependencies=[Depends(require_permission("extraction:trigger"))],
)
async def trigger_extraction(
    document_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ExtractionService, Depends(get_extraction_service)],
) -> ApiResponse[ExtractionRunRead]:
    run = await service.trigger_extraction(document_id, requested_by=current_user.id)
    return ApiResponse(data=ExtractionRunRead.model_validate(run))


@router.get(
    "/{document_id}/entities",
    response_model=PaginatedResponse[ExtractedEntityRead],
    dependencies=[Depends(require_permission("extraction:read"))],
)
async def list_entities(
    document_id: uuid.UUID,
    service: Annotated[ExtractionService, Depends(get_extraction_service)],
    page: int = 1,
    page_size: int = 50,
) -> PaginatedResponse[ExtractedEntityRead]:
    entities, total = await service.list_entities(
        document_id, offset=(page - 1) * page_size, limit=page_size
    )
    return PaginatedResponse(
        data=[ExtractedEntityRead.model_validate(e) for e in entities],
        meta=PageMeta(
            page=page,
            page_size=page_size,
            total_items=total,
            total_pages=max(1, math.ceil(total / page_size)),
        ),
    )


@router.get(
    "/{document_id}/tables",
    response_model=PaginatedResponse[ExtractedTableRead],
    dependencies=[Depends(require_permission("extraction:read"))],
)
async def list_tables(
    document_id: uuid.UUID,
    service: Annotated[ExtractionService, Depends(get_extraction_service)],
    page: int = 1,
    page_size: int = 50,
) -> PaginatedResponse[ExtractedTableRead]:
    tables, total = await service.list_tables(
        document_id, offset=(page - 1) * page_size, limit=page_size
    )
    return PaginatedResponse(
        data=[ExtractedTableRead.model_validate(t) for t in tables],
        meta=PageMeta(
            page=page,
            page_size=page_size,
            total_items=total,
            total_pages=max(1, math.ceil(total / page_size)),
        ),
    )


@runs_router.get(
    "/{extraction_run_id}",
    response_model=ApiResponse[ExtractionRunRead],
    dependencies=[Depends(require_permission("extraction:read"))],
)
async def get_extraction_run(
    extraction_run_id: uuid.UUID,
    service: Annotated[ExtractionService, Depends(get_extraction_service)],
) -> ApiResponse[ExtractionRunRead]:
    run = await service.get_run(extraction_run_id)
    return ApiResponse(data=ExtractionRunRead.model_validate(run))


@tables_router.get(
    "/{table_id}",
    response_model=ApiResponse[ExtractedTableDetailRead],
    dependencies=[Depends(require_permission("extraction:read"))],
)
async def get_extraction_table(
    table_id: uuid.UUID,
    service: Annotated[ExtractionService, Depends(get_extraction_service)],
) -> ApiResponse[ExtractedTableDetailRead]:
    table = await service.get_table(table_id)
    cells = await service.list_cells(table_id)
    detail = ExtractedTableDetailRead(
        **ExtractedTableRead.model_validate(table).model_dump(),
        cells=[TableCellRead.model_validate(c) for c in cells],
    )
    return ApiResponse(data=detail)
