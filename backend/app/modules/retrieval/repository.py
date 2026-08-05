"""Data access for Phase 5's retrieval platform: embeddings (the
polymorphic vector store), and the retrieval_runs/retrieval_results
run-tracking pair. Vector similarity search itself lives in
vector_search.py, not here - it needs pgvector's distance operators in a
raw ORDER BY, a different shape from this file's plain CRUD/lookup
queries, the same reason graph/repository.py separates its recursive-CTE
traversal queries onto GraphEdgeRepository rather than folding them into
generic BaseRepository methods.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.base_repository import BaseRepository
from app.modules.retrieval.models import Embedding, RetrievalResult, RetrievalRun


class EmbeddingRepository(BaseRepository[Embedding]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Embedding)

    async def get_by_source(
        self, *, source_type: str, source_id: str, embedding_provider: str, embedding_model: str
    ) -> Embedding | None:
        """The lookup EmbeddingService runs before generating anything -
        if a row already exists with a matching embedding_hash, generation
        is skipped entirely ("never regenerate identical embeddings")."""
        stmt = select(Embedding).where(
            Embedding.source_type == source_type,
            Embedding.source_id == source_id,
            Embedding.embedding_provider == embedding_provider,
            Embedding.embedding_model == embedding_model,
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_by_sources(
        self, *, source_type: str, source_ids: list[str], embedding_provider: str
    ) -> dict[str, Embedding]:
        """Which of `source_ids` already have an embedding from
        `embedding_provider`, keyed by source_id - used to skip already-
        embedded chunks/nodes/edges in a batch indexing pass without one
        query per source."""
        if not source_ids:
            return {}
        stmt = select(Embedding).where(
            Embedding.source_type == source_type,
            Embedding.source_id.in_(source_ids),
            Embedding.embedding_provider == embedding_provider,
        )
        result = await self.session.execute(stmt)
        return {row.source_id: row for row in result.scalars().all()}


class RetrievalRunRepository(BaseRepository[RetrievalRun]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, RetrievalRun)


class RetrievalResultRepository(BaseRepository[RetrievalResult]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, RetrievalResult)

    async def bulk_create(self, items: list[RetrievalResult]) -> list[RetrievalResult]:
        self.session.add_all(items)
        await self.session.flush()
        return items

    async def list_for_run(self, retrieval_run_id: uuid.UUID) -> list[RetrievalResult]:
        stmt = (
            select(RetrievalResult)
            .where(RetrievalResult.retrieval_run_id == retrieval_run_id)
            .order_by(RetrievalResult.final_rank.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
