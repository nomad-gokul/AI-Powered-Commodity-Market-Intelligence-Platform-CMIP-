"""Audit logging service.

record() is called explicitly from the services that perform sensitive
actions (login, role changes, etc.) rather than via a blanket
"log every request" middleware. A middleware approach logs noise (every
GET /dashboard/summary) alongside signal (a role was revoked) with no way
to tell them apart; explicit calls mean every audit row was put there for
a specific, reviewable reason.
"""

import uuid
from datetime import datetime
from typing import Any

from app.common.base_service import BaseService
from app.modules.audit.models import AuditLog
from app.modules.audit.repository import AuditLogRepository


class AuditService(BaseService):
    def __init__(self, repo: AuditLogRepository) -> None:
        super().__init__()
        self.repo = repo

    async def record(
        self,
        *,
        action: str,
        resource_type: str,
        user_id: uuid.UUID | None = None,
        resource_id: uuid.UUID | None = None,
        metadata: dict[str, Any] | None = None,
        ip_address: str | None = None,
    ) -> AuditLog:
        entry = AuditLog(
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            metadata_=metadata or {},
            ip_address=ip_address,
        )
        created = await self.repo.create(entry)
        self.logger.info("audit_recorded", action=action, resource_type=resource_type)
        return created

    async def search(
        self,
        *,
        user_id: uuid.UUID | None = None,
        action: str | None = None,
        resource_type: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[AuditLog], int]:
        entries = await self.repo.search(
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            date_from=date_from,
            date_to=date_to,
            offset=offset,
            limit=limit,
        )
        total = await self.repo.count(user_id=user_id, action=action, resource_type=resource_type)
        return entries, total
