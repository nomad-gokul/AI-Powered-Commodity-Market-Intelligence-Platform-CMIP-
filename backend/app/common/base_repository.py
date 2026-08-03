"""Generic async repository providing CRUD primitives over a SQLAlchemy model.

Module-specific repositories subclass this and add custom query methods.
Repositories never contain business logic - only data access. Where a
module has a real domain type (see app/modules/<name>/domain.py), the
repository is also responsible for mapping ORM <-> domain on load/save;
where it doesn't, the ORM model is returned directly.
"""

from datetime import datetime
from typing import Any, Protocol, cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped

from app.core.database import Base


class _HasCreatedAt(Protocol):
    """What BaseRepository.list() needs beyond Base: every current model
    either uses TimestampMixin or (like AuditLog) declares created_at
    directly, so this holds in practice - the cast below documents that
    assumption rather than silencing it."""

    created_at: Mapped[datetime]


class BaseRepository[ModelT: Base]:
    def __init__(self, session: AsyncSession, model: type[ModelT]) -> None:
        self.session = session
        self.model = model

    async def get_by_id(self, entity_id: UUID) -> ModelT | None:
        return await self.session.get(self.model, entity_id)

    async def list(self, *, offset: int = 0, limit: int = 20, **filters: Any) -> list[ModelT]:
        stmt = select(self.model)
        for field, value in filters.items():
            if value is not None:
                stmt = stmt.where(getattr(self.model, field) == value)
        timestamped_model = cast(_HasCreatedAt, self.model)
        stmt = stmt.offset(offset).limit(limit).order_by(timestamped_model.created_at.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count(self, **filters: Any) -> int:
        stmt = select(func.count()).select_from(self.model)
        for field, value in filters.items():
            if value is not None:
                stmt = stmt.where(getattr(self.model, field) == value)
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    async def create(self, entity: ModelT) -> ModelT:
        self.session.add(entity)
        await self.session.flush()
        await self.session.refresh(entity)
        return entity

    async def update(self, entity: ModelT, **fields: Any) -> ModelT:
        for key, value in fields.items():
            setattr(entity, key, value)
        await self.session.flush()
        await self.session.refresh(entity)
        return entity

    async def delete(self, entity: ModelT) -> None:
        await self.session.delete(entity)
        await self.session.flush()
