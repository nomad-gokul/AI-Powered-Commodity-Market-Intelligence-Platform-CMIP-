"""HTTP routes for reading the audit log. Admin-only."""

import math
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.schemas import PageMeta, PaginatedResponse
from app.core.database import get_db_session
from app.modules.audit.repository import AuditLogRepository
from app.modules.audit.schemas import AuditLogRead
from app.modules.audit.service import AuditService
from app.modules.auth.dependencies import require_permission

router = APIRouter(prefix="/audit-logs", tags=["Audit"])


def get_audit_service(session: Annotated[AsyncSession, Depends(get_db_session)]) -> AuditService:
    return AuditService(AuditLogRepository(session))


@router.get("", response_model=PaginatedResponse[AuditLogRead])
async def search_audit_logs(
    service: Annotated[AuditService, Depends(get_audit_service)],
    _: Annotated[object, Depends(require_permission("audit_logs:read"))],
    user_id: uuid.UUID | None = None,
    action: str | None = None,
    resource_type: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> PaginatedResponse[AuditLogRead]:
    entries, total = await service.search(
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        date_from=date_from,
        date_to=date_to,
        offset=(page - 1) * page_size,
        limit=page_size,
    )
    return PaginatedResponse(
        data=[AuditLogRead.model_validate(e) for e in entries],
        meta=PageMeta(
            page=page,
            page_size=page_size,
            total_items=total,
            total_pages=max(1, math.ceil(total / page_size)),
        ),
    )
