"""Unit tests for HybridRetriever: merge/dedupe across BM25/vector/graph
branches, source_type filtering, run persistence lifecycle (including the
failure path), and graph-only mode.

Every I/O boundary (repositories, the three search branches, the embedding
provider) is a fake/mock; QueryAnalyzer and RerankerService are the REAL
implementations (built from tiny fixture registries / default weights) so
entity detection and ranking are exercised for real, not mocked away."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from ai_service.retrieval.reranker import RerankerService
from shared.ai_contracts import ProviderHealth
from shared.embedding_contracts import EmbeddingRequest, EmbeddingResponse, EmbeddingUsage

from app.modules.extraction.trust.normalization.canonical_registry import (
    CanonicalEntry,
    CanonicalRegistry,
)
from app.modules.extraction.trust.normalization.loader import CanonicalRegistries
from app.modules.graph.models import GraphEdge, GraphNode, GraphNodeStatus
from app.modules.retrieval.bm25 import BM25Hit
from app.modules.retrieval.graph_expansion import GraphExpansionHit, GraphExpansionResult
from app.modules.retrieval.hybrid_retriever import HybridRetrievalRequest, HybridRetriever
from app.modules.retrieval.models import RetrievalRun, RetrievalRunStatus
from app.modules.retrieval.query_analyzer import QueryAnalyzer
from app.modules.retrieval.vector_search import VectorHit

pytestmark = pytest.mark.asyncio

_NOW = datetime(2026, 6, 1, tzinfo=UTC)


class _FakeEmbeddingProvider:
    def __init__(self) -> None:
        self.embed_calls: list[EmbeddingRequest] = []

    @property
    def name(self) -> str:
        return "fake"

    @property
    def dimension(self) -> int:
        return 3

    @property
    def model(self) -> str:
        return "fake-model"

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        self.embed_calls.append(request)
        return EmbeddingResponse(
            vectors=[[0.1, 0.2, 0.3]],
            provider="fake",
            model=request.model,
            dimension=3,
            usage=EmbeddingUsage(),
            latency_ms=1.0,
        )

    async def health_check(self) -> ProviderHealth:
        return ProviderHealth(healthy=True)


class _FakeRunRepo:
    def __init__(self) -> None:
        self.created: list[RetrievalRun] = []
        self.updated: list[RetrievalRun] = []

    async def create(self, run: RetrievalRun) -> RetrievalRun:
        self.created.append(run)
        return run

    async def update(self, run: RetrievalRun, **fields: object) -> RetrievalRun:
        for key, value in fields.items():
            setattr(run, key, value)
        self.updated.append(run)
        return run


class _FakeResultRepo:
    def __init__(self) -> None:
        self.bulk_created: list[list[object]] = []

    async def bulk_create(self, items: list[object]) -> list[object]:
        self.bulk_created.append(items)
        return items


def _query_analyzer() -> QueryAnalyzer:
    empty = CanonicalRegistry([])
    ports = CanonicalRegistry(
        [
            CanonicalEntry(
                canonical_id="port:mundra", canonical_name="Mundra Port", aliases=("Mundra Port",)
            )
        ]
    )
    registries = CanonicalRegistries(
        countries=empty,
        currencies=empty,
        units=empty,
        incoterms=empty,
        hs_codes=empty,
        commodities=empty,
        ports=ports,
    )
    return QueryAnalyzer(registries=registries, companies=empty)


def _node(canonical_id: str) -> GraphNode:
    return GraphNode(
        id=uuid.uuid4(),
        canonical_id=canonical_id,
        node_type="port",
        display_name=canonical_id,
        aliases_json=[],
        metadata_json={},
        status=GraphNodeStatus.ACTIVE,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _edge(source_id: uuid.UUID, target_id: uuid.UUID, *, confidence: float = 0.8) -> GraphEdge:
    return GraphEdge(
        id=uuid.uuid4(),
        source_node_id=source_id,
        target_node_id=target_id,
        relationship_type="owns",
        confidence=confidence,
        evidence_count=1,
        provenance_json={},
        created_at=_NOW,
        updated_at=_NOW,
    )


def _build_retriever(
    *,
    bm25_hits: list[BM25Hit] | None = None,
    bm25_error: Exception | None = None,
    vector_hits: list[VectorHit] | None = None,
    graph_result: GraphExpansionResult | None = None,
    no_embedding_provider: bool = False,
) -> tuple[HybridRetriever, dict[str, object]]:
    bm25 = AsyncMock()
    if bm25_error is not None:
        bm25.search.side_effect = bm25_error
    else:
        bm25.search.return_value = bm25_hits or []
    vector_search = AsyncMock()
    vector_search.search.return_value = vector_hits or []
    graph_expansion = AsyncMock()
    graph_expansion.expand.return_value = graph_result or GraphExpansionResult(nodes=[], edges=[])
    embedding_provider = None if no_embedding_provider else _FakeEmbeddingProvider()
    run_repo = _FakeRunRepo()
    result_repo = _FakeResultRepo()

    retriever = HybridRetriever(
        query_analyzer=_query_analyzer(),
        bm25=bm25,
        vector_search=vector_search,
        graph_expansion=graph_expansion,
        embedding_provider=embedding_provider,  # type: ignore[arg-type]
        reranker=RerankerService(),
        run_repo=run_repo,  # type: ignore[arg-type]
        result_repo=result_repo,  # type: ignore[arg-type]
    )
    collaborators: dict[str, object] = {
        "bm25": bm25,
        "vector_search": vector_search,
        "graph_expansion": graph_expansion,
        "embedding_provider": embedding_provider,
        "run_repo": run_repo,
        "result_repo": result_repo,
    }
    return retriever, collaborators


class TestRetrieve:
    async def test_merges_chunk_seen_by_both_bm25_and_vector_into_hybrid_method(self) -> None:
        chunk_id = uuid.uuid4()
        bm25_hits = [BM25Hit(chunk_id=chunk_id, document_id=uuid.uuid4(), score=1.5)]
        vector_hits = [
            VectorHit(
                source_type="document_chunk", source_id=str(chunk_id), distance=0.1, similarity=0.9
            )
        ]
        retriever, _ = _build_retriever(bm25_hits=bm25_hits, vector_hits=vector_hits)

        result = await retriever.retrieve(HybridRetrievalRequest(query="port news"))

        assert len(result.candidates) == 1
        candidate = result.candidates[0]
        assert candidate.retrieval_method == "hybrid"
        assert candidate.signals.bm25_score == 1.5
        assert candidate.signals.vector_similarity == 0.9

    async def test_persists_completed_run_with_correct_counts(self) -> None:
        chunk_id = uuid.uuid4()
        bm25_hits = [BM25Hit(chunk_id=chunk_id, document_id=uuid.uuid4(), score=1.0)]
        retriever, collaborators = _build_retriever(bm25_hits=bm25_hits)

        result = await retriever.retrieve(HybridRetrievalRequest(query="test"))

        assert result.run.status == RetrievalRunStatus.COMPLETED
        assert result.run.total_candidates == 1
        assert result.run.retrieved_results == 1
        assert len(collaborators["result_repo"].bulk_created) == 1  # type: ignore[attr-defined]

    async def test_source_types_filter_excludes_disallowed_sources(self) -> None:
        chunk_id = uuid.uuid4()
        bm25_hits = [BM25Hit(chunk_id=chunk_id, document_id=uuid.uuid4(), score=1.0)]
        retriever, _ = _build_retriever(bm25_hits=bm25_hits)

        result = await retriever.retrieve(
            HybridRetrievalRequest(query="test", source_types=("graph_node",))
        )

        assert result.candidates == []

    async def test_graph_expansion_seeded_from_query_analyzer_detected_entities(self) -> None:
        node = _node("port:mundra")
        graph_result = GraphExpansionResult(
            nodes=[GraphExpansionHit(node=node, hop_distance=0, seed_canonical_id="port:mundra")],
            edges=[],
        )
        retriever, collaborators = _build_retriever(graph_result=graph_result)

        result = await retriever.retrieve(HybridRetrievalRequest(query="Mundra Port news"))

        assert any(c.source_type == "graph_node" for c in result.candidates)
        collaborators["graph_expansion"].expand.assert_awaited_once()  # type: ignore[attr-defined]
        called_seeds = collaborators["graph_expansion"].expand.await_args.args[0]  # type: ignore[attr-defined]
        assert "port:mundra" in called_seeds

    async def test_no_query_entities_means_no_graph_expansion_call(self) -> None:
        retriever, collaborators = _build_retriever()

        await retriever.retrieve(HybridRetrievalRequest(query="unrelated text"))

        collaborators["graph_expansion"].expand.assert_not_awaited()  # type: ignore[attr-defined]

    async def test_marks_run_failed_and_reraises_on_branch_error(self) -> None:
        retriever, collaborators = _build_retriever(bm25_error=RuntimeError("db down"))

        with pytest.raises(RuntimeError, match="db down"):
            await retriever.retrieve(HybridRetrievalRequest(query="test"))

        run_repo = collaborators["run_repo"]
        assert run_repo.updated[-1].status == RetrievalRunStatus.FAILED  # type: ignore[attr-defined]
        assert run_repo.updated[-1].error_message == "db down"  # type: ignore[attr-defined]

    async def test_empty_query_returns_no_candidates_without_error(self) -> None:
        retriever, _ = _build_retriever()
        result = await retriever.retrieve(HybridRetrievalRequest(query=""))
        assert result.candidates == []
        assert result.run.status == RetrievalRunStatus.COMPLETED

    async def test_degrades_to_bm25_and_graph_only_without_an_embedding_provider(self) -> None:
        chunk_id = uuid.uuid4()
        bm25_hits = [BM25Hit(chunk_id=chunk_id, document_id=uuid.uuid4(), score=1.0)]
        retriever, collaborators = _build_retriever(
            bm25_hits=bm25_hits, no_embedding_provider=True
        )

        result = await retriever.retrieve(HybridRetrievalRequest(query="test"))

        assert result.run.status == RetrievalRunStatus.COMPLETED
        assert len(result.candidates) == 1
        assert result.run.provider is None
        assert result.run.embedding_model is None
        collaborators["vector_search"].search.assert_not_awaited()  # type: ignore[attr-defined]


class TestRetrieveGraphOnly:
    async def test_skips_bm25_and_vector_entirely(self) -> None:
        node = _node("port:mundra")
        graph_result = GraphExpansionResult(
            nodes=[GraphExpansionHit(node=node, hop_distance=0, seed_canonical_id="port:mundra")],
            edges=[],
        )
        retriever, collaborators = _build_retriever(graph_result=graph_result)

        result = await retriever.retrieve_graph_only(
            query="Mundra Port", seed_canonical_ids=["port:mundra"]
        )

        assert len(result.candidates) == 1
        collaborators["bm25"].search.assert_not_awaited()  # type: ignore[attr-defined]
        collaborators["vector_search"].search.assert_not_awaited()  # type: ignore[attr-defined]
        embedding_provider = collaborators["embedding_provider"]
        assert embedding_provider.embed_calls == []  # type: ignore[attr-defined]

    async def test_includes_edges_with_relationship_confidence_signal(self) -> None:
        source = _node("port:mundra")
        target = _node("company:adani_ports_sez")
        edge = _edge(source.id, target.id, confidence=0.75)
        graph_result = GraphExpansionResult(
            nodes=[
                GraphExpansionHit(node=source, hop_distance=0, seed_canonical_id="port:mundra"),
                GraphExpansionHit(node=target, hop_distance=1, seed_canonical_id="port:mundra"),
            ],
            edges=[edge],
        )
        retriever, _ = _build_retriever(graph_result=graph_result)

        result = await retriever.retrieve_graph_only(
            query="", seed_canonical_ids=["port:mundra"]
        )

        edge_candidates = [c for c in result.candidates if c.source_type == "graph_edge"]
        assert len(edge_candidates) == 1
        assert edge_candidates[0].signals.relationship_confidence == 0.75
