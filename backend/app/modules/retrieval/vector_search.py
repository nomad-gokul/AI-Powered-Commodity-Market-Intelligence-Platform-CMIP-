"""VectorSearch: pgvector similarity search over the embeddings table.

Supports cosine, L2, and inner-product distance - pgvector-python's
Vector column exposes `.cosine_distance()`/`.l2_distance()`/
`.max_inner_product()` comparator methods directly usable in a normal
`select()`, so this needs no raw-SQL vector literal building. Only cosine
has a matching HNSW index (see app.modules.retrieval.models); L2/
inner-product queries are correct but not index-accelerated - a disclosed,
deliberate scope decision (see docs/ARCHITECTURE.md's Phase 5 section:
"HNSW built by default; IVFFlat documented but not built"), not an
oversight.
"""

import time
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import ColumnElement, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.metrics import vector_search_duration_seconds
from app.modules.retrieval.models import Embedding


class DistanceMetric(StrEnum):
    COSINE = "cosine"
    L2 = "l2"
    INNER_PRODUCT = "inner_product"


@dataclass(frozen=True, slots=True)
class VectorHit:
    source_type: str
    source_id: str
    distance: float
    similarity: float
    """A higher-is-better score derived from distance: 1 - distance for
    cosine (bounded roughly [0, 2] in theory, [0, 1] in practice for
    normalized embeddings), -distance for L2/inner product (unbounded -
    RerankerService's normalization clamps it, see
    ai_service.retrieval.reranker)."""


class VectorSearch:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def search(
        self,
        query_vector: list[float],
        *,
        metric: DistanceMetric = DistanceMetric.COSINE,
        source_type: str | None = None,
        limit: int = 50,
    ) -> list[VectorHit]:
        started = time.monotonic()
        distance_expr = self._distance_expression(metric, query_vector)
        stmt = select(
            Embedding.source_type, Embedding.source_id, distance_expr.label("distance")
        )
        if source_type is not None:
            stmt = stmt.where(Embedding.source_type == source_type)
        stmt = stmt.order_by(distance_expr.asc()).limit(limit)

        result = await self._session.execute(stmt)
        hits: list[VectorHit] = []
        for row in result:
            distance = float(row.distance)
            similarity = (1.0 - distance) if metric == DistanceMetric.COSINE else -distance
            hits.append(
                VectorHit(
                    source_type=row.source_type.value,
                    source_id=row.source_id,
                    distance=distance,
                    similarity=similarity,
                )
            )
        vector_search_duration_seconds.observe(time.monotonic() - started)
        return hits

    @staticmethod
    def _distance_expression(
        metric: DistanceMetric, query_vector: list[float]
    ) -> ColumnElement[float]:
        column = Embedding.embedding_vector
        if metric == DistanceMetric.COSINE:
            return column.cosine_distance(query_vector)  # type: ignore[no-any-return]
        if metric == DistanceMetric.L2:
            return column.l2_distance(query_vector)  # type: ignore[no-any-return]
        return column.max_inner_product(query_vector)  # type: ignore[no-any-return]
