"""Data access for extraction runs, entities, mentions, tables, and cells."""

import uuid
from typing import Any

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.base_repository import BaseRepository
from app.modules.extraction.models import (
    EntityMention,
    ExtractedEntity,
    ExtractedTable,
    ExtractionRun,
    ExtractionStatus,
    TableCell,
)


class ExtractionRunRepository(BaseRepository[ExtractionRun]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, ExtractionRun)

    async def list_for_document(self, document_id: uuid.UUID) -> list[ExtractionRun]:
        stmt = (
            select(ExtractionRun)
            .where(ExtractionRun.document_id == document_id)
            .order_by(ExtractionRun.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def find_completed_by_fingerprint(self, fingerprint: str) -> ExtractionRun | None:
        """Phase 3.3's extraction fingerprint dedup: a COMPLETED run with
        this exact (document content, prompts, pipeline version, provider,
        model) combination means re-running would produce the same
        result - trigger_extraction returns this run instead of paying
        for the LLM calls again."""
        stmt = (
            select(ExtractionRun)
            .where(ExtractionRun.extraction_fingerprint == fingerprint)
            .where(ExtractionRun.status == ExtractionStatus.COMPLETED)
            .order_by(ExtractionRun.completed_at.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()


class ExtractedEntityRepository(BaseRepository[ExtractedEntity]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, ExtractedEntity)

    async def delete_for_run(self, extraction_run_id: uuid.UUID) -> None:
        """Used before re-persisting a run's entities so a retry of the
        Persist step replaces rather than duplicates them - same
        idempotency pattern as DocumentChunkRepository.delete_for_document
        in Phase 2."""
        await self.session.execute(
            sa_delete(ExtractedEntity).where(ExtractedEntity.extraction_run_id == extraction_run_id)
        )
        await self.session.flush()

    async def bulk_create(self, entities: list[ExtractedEntity]) -> list[ExtractedEntity]:
        self.session.add_all(entities)
        await self.session.flush()
        return entities

    async def list_for_run(
        self, extraction_run_id: uuid.UUID, *, offset: int = 0, limit: int = 100
    ) -> list[ExtractedEntity]:
        stmt = (
            select(ExtractedEntity)
            .where(ExtractedEntity.extraction_run_id == extraction_run_id)
            .order_by(ExtractedEntity.created_at.asc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_all_for_run(self, extraction_run_id: uuid.UUID) -> list[ExtractedEntity]:
        """Unpaginated - for Phase 3.3's trust pipeline, which needs every
        entity a run produced at once (to evaluate cross-entity rules,
        score each one, and normalize each one), not a page of them."""
        stmt = select(ExtractedEntity).where(
            ExtractedEntity.extraction_run_id == extraction_run_id
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_for_document(
        self, document_id: uuid.UUID, *, offset: int = 0, limit: int = 100
    ) -> list[ExtractedEntity]:
        """Entities from the document's most recent extraction run."""
        stmt = (
            select(ExtractedEntity)
            .join(ExtractionRun, ExtractedEntity.extraction_run_id == ExtractionRun.id)
            .where(ExtractionRun.document_id == document_id)
            .where(ExtractionRun.id == _latest_run_subquery(document_id))
            .order_by(ExtractedEntity.created_at.asc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_for_document(self, document_id: uuid.UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(ExtractedEntity)
            .join(ExtractionRun, ExtractedEntity.extraction_run_id == ExtractionRun.id)
            .where(ExtractionRun.document_id == document_id)
            .where(ExtractionRun.id == _latest_run_subquery(document_id))
        )
        result = await self.session.execute(stmt)
        return int(result.scalar_one())


class EntityMentionRepository(BaseRepository[EntityMention]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, EntityMention)

    async def bulk_create(self, mentions: list[EntityMention]) -> list[EntityMention]:
        self.session.add_all(mentions)
        await self.session.flush()
        return mentions

    async def list_for_entities(
        self, entity_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, list[EntityMention]]:
        """Every mention for a set of entities, grouped by entity_id -
        avoids an N+1 query when Phase 4's graph builder needs every
        entity's mentions at once to find same-chunk co-occurrences."""
        if not entity_ids:
            return {}
        stmt = select(EntityMention).where(EntityMention.entity_id.in_(entity_ids))
        result = await self.session.execute(stmt)
        grouped: dict[uuid.UUID, list[EntityMention]] = {entity_id: [] for entity_id in entity_ids}
        for mention in result.scalars().all():
            grouped[mention.entity_id].append(mention)
        return grouped


class ExtractedTableRepository(BaseRepository[ExtractedTable]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, ExtractedTable)

    async def delete_for_run(self, extraction_run_id: uuid.UUID) -> None:
        await self.session.execute(
            sa_delete(ExtractedTable).where(ExtractedTable.extraction_run_id == extraction_run_id)
        )
        await self.session.flush()

    async def bulk_create(self, tables: list[ExtractedTable]) -> list[ExtractedTable]:
        self.session.add_all(tables)
        await self.session.flush()
        return tables

    async def list_for_document(
        self, document_id: uuid.UUID, *, offset: int = 0, limit: int = 100
    ) -> list[ExtractedTable]:
        """Tables from the document's most recent extraction run."""
        stmt = (
            select(ExtractedTable)
            .join(ExtractionRun, ExtractedTable.extraction_run_id == ExtractionRun.id)
            .where(ExtractionRun.document_id == document_id)
            .where(ExtractionRun.id == _latest_run_subquery(document_id))
            .order_by(ExtractedTable.page_number.asc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_for_document(self, document_id: uuid.UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(ExtractedTable)
            .join(ExtractionRun, ExtractedTable.extraction_run_id == ExtractionRun.id)
            .where(ExtractionRun.document_id == document_id)
            .where(ExtractionRun.id == _latest_run_subquery(document_id))
        )
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    async def list_for_run(self, extraction_run_id: uuid.UUID) -> list[ExtractedTable]:
        """Unpaginated, for Phase 3.3's trust pipeline (table-total
        reconciliation needs every table a run produced at once)."""
        stmt = select(ExtractedTable).where(ExtractedTable.extraction_run_id == extraction_run_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class TableCellRepository(BaseRepository[TableCell]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, TableCell)

    async def bulk_create(self, cells: list[TableCell]) -> list[TableCell]:
        self.session.add_all(cells)
        await self.session.flush()
        return cells

    async def list_for_tables(self, table_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[TableCell]]:
        """Every cell for a set of tables, grouped by table_id - avoids an
        N+1 query when a trust-pipeline agent needs every table's cells at
        once."""
        if not table_ids:
            return {}
        stmt = (
            select(TableCell)
            .where(TableCell.table_id.in_(table_ids))
            .order_by(TableCell.row.asc(), TableCell.column.asc())
        )
        result = await self.session.execute(stmt)
        grouped: dict[uuid.UUID, list[TableCell]] = {table_id: [] for table_id in table_ids}
        for cell in result.scalars().all():
            grouped[cell.table_id].append(cell)
        return grouped

    async def list_for_table(self, table_id: uuid.UUID) -> list[TableCell]:
        stmt = (
            select(TableCell)
            .where(TableCell.table_id == table_id)
            .order_by(TableCell.row.asc(), TableCell.column.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


def _latest_run_subquery(document_id: uuid.UUID) -> Any:
    return (
        select(ExtractionRun.id)
        .where(ExtractionRun.document_id == document_id)
        .order_by(ExtractionRun.created_at.desc())
        .limit(1)
        .scalar_subquery()
    )
