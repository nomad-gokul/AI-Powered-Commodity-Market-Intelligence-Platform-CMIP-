"""HybridRetriever: orchestrates BM25 + vector search + knowledge-graph
expansion into one ranked, cited result set - Phase 5's central pipeline.

    Query
      |
      v
   QueryAnalyzer (deterministic: intent/entities/time-range/filters)
      |
      +--> BM25Search (document_chunks.text_search)
      +--> VectorSearch (embeddings, cosine by default)
      +--> GraphExpansion (seeded from QueryAnalyzer's detected entities)
      |
      v
    merge + dedupe (by source_type, source_id) - a candidate seen by more
    than one method is labeled "hybrid" and keeps every method's signal
      |
      v
    RerankerService (ai-service, pure scoring)
      |
      v
    top-K, persisted as one RetrievalRun + its RetrievalResults

Runs its three branches sequentially, not concurrently via asyncio.gather:
they share one AsyncSession, and SQLAlchemy's AsyncSession is not safe for
concurrent use from multiple coroutines.

Disclosed scope decision: RerankSignals.entity_trust/document_quality are
never populated here (they'd need a join into trust's ConfidenceScore per
entity-in-chunk, and there is no stored "document quality" field anywhere
in the schema) - they stay None, which RerankerService's weighted-average-
of-present-signals already handles correctly, rather than inventing a
number. recency IS populated, from data already in hand (no extra query).

embedding_provider is Optional: retrieve_graph_only() never calls it (a
seed-canonical-id graph expansion needs no embedding at all), and retrieve()
degrades to BM25+graph-only when it's None (the vector branch is simply
skipped) rather than failing the whole request - see api.py's
get_hybrid_retriever/require_embedding_provider split for where an
unconfigured provider becomes a clear 503 for the two routes that
genuinely need it (/retrieve, /retrieve/context), while /retrieve/graph
stays available regardless.
"""

import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from ai_service.embeddings.base import EmbeddingProvider
from ai_service.retrieval.reranker import RerankerService
from shared.embedding_contracts import EmbeddingRequest
from shared.retrieval_contracts import RerankSignals, RetrievalCandidate

from app.core.metrics import retrieval_run_duration_seconds
from app.modules.retrieval.bm25 import BM25Search
from app.modules.retrieval.graph_expansion import GraphExpansion
from app.modules.retrieval.models import (
    EmbeddingSourceType,
    RetrievalMethod,
    RetrievalResult,
    RetrievalRun,
    RetrievalRunStatus,
)
from app.modules.retrieval.query_analyzer import QueryAnalysis, QueryAnalyzer
from app.modules.retrieval.repository import RetrievalResultRepository, RetrievalRunRepository
from app.modules.retrieval.vector_search import DistanceMetric, VectorSearch

_RECENCY_HALF_LIFE_DAYS = 90.0
_CandidateMap = dict[tuple[str, str], RetrievalCandidate]


@dataclass(frozen=True, slots=True)
class HybridRetrievalRequest:
    query: str
    top_k: int = 10
    max_candidates: int = 200
    graph_expansion_depth: int = 2
    source_types: tuple[str, ...] | None = None
    requested_by_user_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class HybridRetrievalResult:
    run: RetrievalRun
    candidates: list[RetrievalCandidate]
    analysis: QueryAnalysis


class HybridRetriever:
    def __init__(
        self,
        *,
        query_analyzer: QueryAnalyzer,
        bm25: BM25Search,
        vector_search: VectorSearch,
        graph_expansion: GraphExpansion,
        embedding_provider: EmbeddingProvider | None,
        reranker: RerankerService,
        run_repo: RetrievalRunRepository,
        result_repo: RetrievalResultRepository,
    ) -> None:
        self._query_analyzer = query_analyzer
        self._bm25 = bm25
        self._vector_search = vector_search
        self._graph_expansion = graph_expansion
        self._embedding_provider = embedding_provider
        self._reranker = reranker
        self._run_repo = run_repo
        self._result_repo = result_repo

    async def retrieve(self, request: HybridRetrievalRequest) -> HybridRetrievalResult:
        async def _collect() -> tuple[_CandidateMap, QueryAnalysis]:
            analysis = self._query_analyzer.analyze(request.query)
            candidates = await self._collect_candidates(request, analysis)
            return candidates, analysis

        return await self._run_pipeline(
            query=request.query,
            requested_by_user_id=request.requested_by_user_id,
            top_k=request.top_k,
            collect=_collect,
        )

    async def retrieve_graph_only(
        self,
        *,
        query: str,
        seed_canonical_ids: list[str] | None = None,
        top_k: int = 10,
        depth: int = 2,
        requested_by_user_id: uuid.UUID | None = None,
    ) -> HybridRetrievalResult:
        async def _collect() -> tuple[_CandidateMap, QueryAnalysis]:
            analysis = self._query_analyzer.analyze(query)
            seeds = seed_canonical_ids or [e.canonical_id for e in analysis.entities]
            candidates = await self._collect_graph_candidates(seeds, depth=depth, source_types=None)
            return candidates, analysis

        return await self._run_pipeline(
            query=query, requested_by_user_id=requested_by_user_id, top_k=top_k, collect=_collect
        )

    # -- pipeline lifecycle --------------------------------------------------

    async def _run_pipeline(
        self,
        *,
        query: str,
        requested_by_user_id: uuid.UUID | None,
        top_k: int,
        collect: Callable[[], Awaitable[tuple[_CandidateMap, QueryAnalysis]]],
    ) -> HybridRetrievalResult:
        started = time.monotonic()
        run = await self._run_repo.create(
            RetrievalRun(
                id=uuid.uuid4(),
                query=query,
                status=RetrievalRunStatus.RUNNING,
                requested_by_user_id=requested_by_user_id,
                total_candidates=0,
                retrieved_results=0,
            )
        )
        try:
            candidates_by_key, analysis = await collect()
            total_candidates = len(candidates_by_key)
            ranked = self._reranker.rerank(list(candidates_by_key.values()))
            top = ranked[:top_k]
            await self._persist_results(run.id, top)

            elapsed_seconds = time.monotonic() - started
            latency_ms = int(elapsed_seconds * 1000)
            retrieval_run_duration_seconds.observe(elapsed_seconds)
            await self._run_repo.update(
                run,
                status=RetrievalRunStatus.COMPLETED,
                provider=self._embedding_provider.name if self._embedding_provider else None,
                embedding_model=self._embedding_provider.model
                if self._embedding_provider
                else None,
                reranker="weighted_linear",
                latency_ms=latency_ms,
                total_candidates=total_candidates,
                retrieved_results=len(top),
            )
            return HybridRetrievalResult(run=run, candidates=top, analysis=analysis)
        except Exception as exc:
            await self._run_repo.update(
                run, status=RetrievalRunStatus.FAILED, error_message=str(exc)
            )
            raise

    # -- candidate collection -------------------------------------------------

    async def _collect_candidates(
        self, request: HybridRetrievalRequest, analysis: QueryAnalysis
    ) -> _CandidateMap:
        candidates: _CandidateMap = {}

        if _source_allowed("document_chunk", request.source_types):
            for hit in await self._bm25.search(request.query, limit=request.max_candidates):
                key = ("document_chunk", str(hit.chunk_id))
                candidates[key] = _merge_candidate(
                    candidates.get(key),
                    source_type="document_chunk",
                    source_id=str(hit.chunk_id),
                    method=RetrievalMethod.BM25,
                    score=hit.score,
                    signals_update={"bm25_score": hit.score},
                )

        if self._embedding_provider is not None and _any_source_allowed(request.source_types):
            embedding_response = await self._embedding_provider.embed(
                EmbeddingRequest(texts=[request.query], model=self._embedding_provider.model)
            )
            query_vector = embedding_response.vectors[0]
            for vector_hit in await self._vector_search.search(
                query_vector, metric=DistanceMetric.COSINE, limit=request.max_candidates
            ):
                if not _source_allowed(vector_hit.source_type, request.source_types):
                    continue
                key = (vector_hit.source_type, vector_hit.source_id)
                candidates[key] = _merge_candidate(
                    candidates.get(key),
                    source_type=vector_hit.source_type,
                    source_id=vector_hit.source_id,
                    method=RetrievalMethod.VECTOR,
                    score=vector_hit.similarity,
                    signals_update={"vector_similarity": vector_hit.similarity},
                )

        seed_canonical_ids = [
            e.canonical_id
            for e in analysis.entities
            if e.entity_type in ("company", "country", "port", "commodity")
        ]
        if seed_canonical_ids:
            graph_candidates = await self._collect_graph_candidates(
                seed_canonical_ids,
                depth=request.graph_expansion_depth,
                source_types=request.source_types,
            )
            for key, candidate in graph_candidates.items():
                candidates[key] = _merge_from_candidate(candidates.get(key), candidate)

        return candidates

    async def _collect_graph_candidates(
        self, seed_canonical_ids: list[str], *, depth: int, source_types: tuple[str, ...] | None
    ) -> _CandidateMap:
        candidates: _CandidateMap = {}
        if not seed_canonical_ids:
            return candidates

        expansion = await self._graph_expansion.expand(seed_canonical_ids, depth=depth)
        for hit in expansion.nodes:
            if not _source_allowed("graph_node", source_types):
                continue
            key = ("graph_node", str(hit.node.id))
            candidates[key] = _merge_candidate(
                candidates.get(key),
                source_type="graph_node",
                source_id=str(hit.node.id),
                method=RetrievalMethod.GRAPH_EXPANSION,
                score=1.0 / (1.0 + hit.hop_distance),
                signals_update={
                    "graph_distance": hit.hop_distance,
                    "recency": _recency_score(hit.node.updated_at),
                },
            )
        for edge in expansion.edges:
            if not _source_allowed("graph_edge", source_types):
                continue
            key = ("graph_edge", str(edge.id))
            candidates[key] = _merge_candidate(
                candidates.get(key),
                source_type="graph_edge",
                source_id=str(edge.id),
                method=RetrievalMethod.GRAPH_EXPANSION,
                score=edge.confidence,
                signals_update={
                    "relationship_confidence": edge.confidence,
                    "recency": _recency_score(edge.updated_at),
                },
            )
        return candidates

    async def _persist_results(self, run_id: uuid.UUID, ranked: list[RetrievalCandidate]) -> None:
        rows = [
            RetrievalResult(
                id=uuid.uuid4(),
                retrieval_run_id=run_id,
                source_type=EmbeddingSourceType(candidate.source_type),
                source_id=candidate.source_id,
                retrieval_method=RetrievalMethod(candidate.retrieval_method),
                score=candidate.score,
                rerank_score=candidate.rerank_score,
                final_rank=candidate.final_rank or (index + 1),
            )
            for index, candidate in enumerate(ranked)
        ]
        if rows:
            await self._result_repo.bulk_create(rows)


def _source_allowed(source_type: str, allowed: tuple[str, ...] | None) -> bool:
    return allowed is None or source_type in allowed


def _any_source_allowed(allowed: tuple[str, ...] | None) -> bool:
    return allowed is None or any(_source_allowed(st.value, allowed) for st in EmbeddingSourceType)


def _recency_score(timestamp: datetime) -> float:
    """Exponential decay: 1.0 at age 0, 0.5 at _RECENCY_HALF_LIFE_DAYS."""
    reference = timestamp if timestamp.tzinfo else timestamp.replace(tzinfo=UTC)
    age_days = max(0.0, (datetime.now(UTC) - reference).total_seconds() / 86400.0)
    decayed: float = 0.5 ** (age_days / _RECENCY_HALF_LIFE_DAYS)
    return decayed


def _merge_candidate(
    existing: RetrievalCandidate | None,
    *,
    source_type: str,
    source_id: str,
    method: RetrievalMethod,
    score: float,
    signals_update: dict[str, float | int],
) -> RetrievalCandidate:
    if existing is None:
        return RetrievalCandidate(
            source_type=source_type,
            source_id=source_id,
            retrieval_method=method.value,
            score=score,
            signals=RerankSignals(**signals_update),
        )
    merged_signals = existing.signals.model_copy(update=signals_update)
    merged_method = (
        existing.retrieval_method if existing.retrieval_method == method.value else "hybrid"
    )
    return existing.model_copy(
        update={
            "signals": merged_signals,
            "retrieval_method": merged_method,
            "score": max(existing.score, score),
        }
    )


def _merge_from_candidate(
    existing: RetrievalCandidate | None, incoming: RetrievalCandidate
) -> RetrievalCandidate:
    if existing is None:
        return incoming
    merged_signals = existing.signals.model_copy(
        update=incoming.signals.model_dump(exclude_none=True)
    )
    merged_method = (
        existing.retrieval_method
        if existing.retrieval_method == incoming.retrieval_method
        else "hybrid"
    )
    return existing.model_copy(
        update={
            "signals": merged_signals,
            "retrieval_method": merged_method,
            "score": max(existing.score, incoming.score),
        }
    )
