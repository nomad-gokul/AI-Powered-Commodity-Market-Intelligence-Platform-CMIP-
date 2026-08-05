"""BM25Search: PostgreSQL full-text search over document_chunks'
generated text_search tsvector column (see app.modules.documents.models).

Uses websearch_to_tsquery, not plainto_tsquery/to_tsquery - it accepts the
same query syntax an end user already expects from a search engine
("quoted phrases", -exclusions, AND implied between bare words) rather
than requiring Postgres's own tsquery operator syntax, and never raises on
malformed input (unmatched quotes are stripped, not a syntax error).
ts_rank_cd (cover density) ranks by term proximity/clustering, not just
term presence/frequency, closer to real "phrase search" relevance than
plain ts_rank.
"""

import time
import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.metrics import bm25_search_duration_seconds


@dataclass(frozen=True, slots=True)
class BM25Hit:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    score: float


class BM25Search:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def search(self, query: str, *, limit: int = 50) -> list[BM25Hit]:
        if not query.strip():
            return []
        started = time.monotonic()
        sql = text(
            """
            SELECT id, document_id,
                   ts_rank_cd(text_search, websearch_to_tsquery('english', :query)) AS score
            FROM document_chunks
            WHERE text_search @@ websearch_to_tsquery('english', :query)
            ORDER BY score DESC
            LIMIT :limit
            """
        )
        result = await self._session.execute(sql, {"query": query, "limit": limit})
        hits = [
            BM25Hit(chunk_id=row.id, document_id=row.document_id, score=float(row.score))
            for row in result
        ]
        bm25_search_duration_seconds.observe(time.monotonic() - started)
        return hits
