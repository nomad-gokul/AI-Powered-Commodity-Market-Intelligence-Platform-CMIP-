"""Unit tests for ContextBuilder: pure assembly of already-fetched Context*
DTOs into one RetrievalContext, with a correct citation list and item
count."""

from shared.retrieval_contracts import (
    Citation,
    ContextChunk,
    ContextGraphNode,
    ContextValidationResult,
)

from ai_service.context.builder import ContextBuilder, get_context_builder


def _citation(source_id: str) -> Citation:
    return Citation(source_type="document_chunk", source_id=source_id)


class TestBuild:
    def test_empty_inputs_produce_empty_context(self) -> None:
        context = ContextBuilder().build(query="who owns mundra port?")
        assert context.total_items == 0
        assert context.citations == []

    def test_combines_heterogeneous_sources_into_one_citation_list(self) -> None:
        chunk = ContextChunk(
            chunk_id="chunk-1",
            document_id="doc-1",
            page_number=1,
            text="Adani Ports SEZ owns Mundra Port.",
            citation=_citation("chunk-1"),
        )
        node = ContextGraphNode(
            node_id="node-1",
            canonical_id="company:adani_ports_sez",
            node_type="company",
            display_name="Adani Ports SEZ",
            citation=_citation("node-1"),
        )
        context = ContextBuilder().build(
            query="who owns mundra port?", chunks=[chunk], graph_nodes=[node]
        )
        assert context.total_items == 2
        assert len(context.citations) == 2
        assert {c.source_id for c in context.citations} == {"chunk-1", "node-1"}

    def test_validation_results_counted_but_not_cited(self) -> None:
        validation = ContextValidationResult(
            validation_result_id="vr-1",
            entity_id="entity-1",
            validation_rule="currency_range",
            severity="warning",
            passed=False,
            message="value out of expected range",
        )
        context = ContextBuilder().build(
            query="q", validation_results=[validation]
        )
        assert context.total_items == 1
        assert context.citations == []


class TestGetContextBuilder:
    def test_returns_cached_singleton(self) -> None:
        assert get_context_builder() is get_context_builder()
