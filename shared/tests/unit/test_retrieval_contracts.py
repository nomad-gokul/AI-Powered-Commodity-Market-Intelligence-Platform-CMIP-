from shared.retrieval_contracts import (
    Citation,
    ContextChunk,
    RerankSignals,
    RetrievalCandidate,
    RetrievalContext,
    RetrievalResultItem,
)


def _citation(**overrides: object) -> Citation:
    defaults: dict[str, object] = {"source_type": "document_chunk", "source_id": "chunk-1"}
    defaults.update(overrides)
    return Citation(**defaults)  # type: ignore[arg-type]


class TestRerankSignals:
    def test_all_signals_optional(self) -> None:
        signals = RerankSignals()
        assert signals.vector_similarity is None
        assert signals.bm25_score is None

    def test_partial_signals(self) -> None:
        signals = RerankSignals(vector_similarity=0.82, bm25_score=None, graph_distance=2)
        assert signals.vector_similarity == 0.82
        assert signals.graph_distance == 2


class TestCitation:
    def test_never_anonymous_requires_source_identity(self) -> None:
        citation = _citation(document_id="doc-1", page_number=3)
        assert citation.source_type == "document_chunk"
        assert citation.source_id == "chunk-1"
        assert citation.document_id == "doc-1"

    def test_graph_path_defaults_empty(self) -> None:
        citation = _citation()
        assert citation.graph_path == []
        assert citation.evidence_ids == []


class TestRetrievalCandidate:
    def test_defaults_have_no_rerank_score_yet(self) -> None:
        candidate = RetrievalCandidate(
            source_type="graph_node",
            source_id="node-1",
            retrieval_method="graph_expansion",
            score=0.5,
        )
        assert candidate.rerank_score is None
        assert candidate.final_rank is None
        assert isinstance(candidate.signals, RerankSignals)


class TestRetrievalResultItem:
    def test_pairs_candidate_with_citation(self) -> None:
        candidate = RetrievalCandidate(
            source_type="document_chunk",
            source_id="chunk-1",
            retrieval_method="bm25",
            score=1.2,
        )
        item = RetrievalResultItem(candidate=candidate, citation=_citation())
        assert item.candidate.source_id == item.citation.source_id


class TestRetrievalContext:
    def test_empty_context_has_zero_items(self) -> None:
        context = RetrievalContext(query="who owns mundra port?")
        assert context.total_items == 0
        assert context.chunks == []
        assert context.graph_nodes == []

    def test_combines_heterogeneous_sources(self) -> None:
        chunk = ContextChunk(
            chunk_id="chunk-1",
            document_id="doc-1",
            page_number=1,
            text="Adani Ports SEZ owns Mundra Port.",
            citation=_citation(document_id="doc-1", page_number=1),
        )
        context = RetrievalContext(query="who owns mundra port?", chunks=[chunk], total_items=1)
        assert context.chunks[0].text.startswith("Adani")
        assert context.total_items == 1
