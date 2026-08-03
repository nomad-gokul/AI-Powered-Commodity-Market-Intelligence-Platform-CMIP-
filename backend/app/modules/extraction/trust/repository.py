"""Data access for the trust layer: trust pipeline runs, validation
results, confidence scores, normalization results, and the review queue.
"""

import uuid
from typing import Any

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.base_repository import BaseRepository
from app.modules.extraction.models import ExtractedEntity, ExtractionStatus
from app.modules.extraction.trust.models import (
    ConfidenceScore,
    NormalizationResult,
    ReviewQueueItem,
    ReviewStatus,
    TrustPipelineRun,
    ValidationResult,
)


class TrustPipelineRunRepository(BaseRepository[TrustPipelineRun]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, TrustPipelineRun)

    async def list_for_extraction_run(self, extraction_run_id: uuid.UUID) -> list[TrustPipelineRun]:
        stmt = (
            select(TrustPipelineRun)
            .where(TrustPipelineRun.extraction_run_id == extraction_run_id)
            .order_by(TrustPipelineRun.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def latest_for_extraction_run(
        self, extraction_run_id: uuid.UUID
    ) -> TrustPipelineRun | None:
        stmt = (
            select(TrustPipelineRun)
            .where(TrustPipelineRun.extraction_run_id == extraction_run_id)
            .order_by(TrustPipelineRun.created_at.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_latest_completed(self) -> list[TrustPipelineRun]:
        """The latest COMPLETED trust run per extraction_run_id - Phase
        4's full-corpus graph rebuild uses this to find every extraction
        run whose entities are trusted and eligible for graph building
        (a run re-validated multiple times only counts once, via its
        most recent completion)."""
        latest_per_run = (
            select(
                TrustPipelineRun.extraction_run_id,
                func.max(TrustPipelineRun.completed_at).label("max_completed_at"),
            )
            .where(TrustPipelineRun.status == ExtractionStatus.COMPLETED)
            .group_by(TrustPipelineRun.extraction_run_id)
            .subquery()
        )
        stmt = select(TrustPipelineRun).join(
            latest_per_run,
            (TrustPipelineRun.extraction_run_id == latest_per_run.c.extraction_run_id)
            & (TrustPipelineRun.completed_at == latest_per_run.c.max_completed_at),
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class ValidationResultRepository(BaseRepository[ValidationResult]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, ValidationResult)

    async def delete_for_run(self, extraction_run_id: uuid.UUID) -> None:
        await self.session.execute(
            sa_delete(ValidationResult).where(
                ValidationResult.extraction_run_id == extraction_run_id
            )
        )
        await self.session.flush()

    async def bulk_create(self, results: list[ValidationResult]) -> list[ValidationResult]:
        self.session.add_all(results)
        await self.session.flush()
        return results

    async def list_for_run(
        self, extraction_run_id: uuid.UUID, *, offset: int = 0, limit: int = 100
    ) -> list[ValidationResult]:
        stmt = (
            select(ValidationResult)
            .where(ValidationResult.extraction_run_id == extraction_run_id)
            .order_by(ValidationResult.created_at.asc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_for_run(self, extraction_run_id: uuid.UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(ValidationResult)
            .where(ValidationResult.extraction_run_id == extraction_run_id)
        )
        result = await self.session.execute(stmt)
        return int(result.scalar_one())


class ConfidenceScoreRepository(BaseRepository[ConfidenceScore]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, ConfidenceScore)

    async def delete_for_run(self, extraction_run_id: uuid.UUID) -> None:
        await self.session.execute(
            sa_delete(ConfidenceScore).where(
                ConfidenceScore.entity_id.in_(_entity_ids_for_run(extraction_run_id))
            )
        )
        await self.session.flush()

    async def bulk_create(self, scores: list[ConfidenceScore]) -> list[ConfidenceScore]:
        self.session.add_all(scores)
        await self.session.flush()
        return scores

    async def list_for_entities(
        self, entity_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, ConfidenceScore]:
        """entity_id -> its ConfidenceScore, for a batch of entities -
        Phase 4's graph builder needs each candidate entity's
        overall_score to scale a relationship's confidence, without an
        N+1 query per entity."""
        if not entity_ids:
            return {}
        stmt = select(ConfidenceScore).where(ConfidenceScore.entity_id.in_(entity_ids))
        result = await self.session.execute(stmt)
        return {score.entity_id: score for score in result.scalars().all()}


class NormalizationResultRepository(BaseRepository[NormalizationResult]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, NormalizationResult)

    async def delete_for_run(self, extraction_run_id: uuid.UUID) -> None:
        await self.session.execute(
            sa_delete(NormalizationResult).where(
                NormalizationResult.entity_id.in_(_entity_ids_for_run(extraction_run_id))
            )
        )
        await self.session.flush()

    async def bulk_create(self, results: list[NormalizationResult]) -> list[NormalizationResult]:
        self.session.add_all(results)
        await self.session.flush()
        return results

    async def list_for_entities(
        self, entity_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, NormalizationResult]:
        """entity_id -> its NormalizationResult, for a batch of entities -
        Phase 4's graph builder needs each candidate entity's
        canonical_id (node identity) and normalization confidence at
        once, without an N+1 query per entity."""
        if not entity_ids:
            return {}
        stmt = select(NormalizationResult).where(NormalizationResult.entity_id.in_(entity_ids))
        result = await self.session.execute(stmt)
        return {item.entity_id: item for item in result.scalars().all()}


class ReviewQueueRepository(BaseRepository[ReviewQueueItem]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, ReviewQueueItem)

    async def delete_for_run(self, extraction_run_id: uuid.UUID) -> None:
        await self.session.execute(
            sa_delete(ReviewQueueItem).where(ReviewQueueItem.extraction_run_id == extraction_run_id)
        )
        await self.session.flush()

    async def bulk_create(self, items: list[ReviewQueueItem]) -> list[ReviewQueueItem]:
        self.session.add_all(items)
        await self.session.flush()
        return items

    async def list_queue(
        self,
        *,
        status: ReviewStatus | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[ReviewQueueItem]:
        stmt = select(ReviewQueueItem).order_by(ReviewQueueItem.created_at.asc())
        if status is not None:
            stmt = stmt.where(ReviewQueueItem.status == status)
        stmt = stmt.offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_queue(self, *, status: ReviewStatus | None = None) -> int:
        stmt = select(func.count()).select_from(ReviewQueueItem)
        if status is not None:
            stmt = stmt.where(ReviewQueueItem.status == status)
        result = await self.session.execute(stmt)
        return int(result.scalar_one())


def _entity_ids_for_run(extraction_run_id: uuid.UUID) -> Any:
    """A subquery of entity ids for one extraction run, meant for use with
    `.in_()` - confidence_scores/normalization_results have no
    extraction_run_id column of their own (entity_id is their primary
    key), so scoping a delete/aggregate to "this run" always goes through
    extracted_entities."""
    return select(ExtractedEntity.id).where(ExtractedEntity.extraction_run_id == extraction_run_id)
