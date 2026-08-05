"""Unit tests for QueryAnalyzer: entity detection (both static-registry and
graph-derived company detection), intent/question-type heuristics, and
time-range parsing. Fully synchronous, no database - both CanonicalRegistry
sources are built from plain fixture data, mirroring how the real DI layer
builds the companies registry from a fresh GraphNodeRepository query
before constructing a QueryAnalyzer."""

import uuid
from datetime import UTC, datetime

from app.modules.extraction.trust.normalization.canonical_registry import (
    CanonicalEntry,
    CanonicalRegistry,
)
from app.modules.extraction.trust.normalization.loader import CanonicalRegistries
from app.modules.graph.models import GraphNode, GraphNodeStatus
from app.modules.retrieval.query_analyzer import (
    QueryAnalyzer,
    QueryIntent,
    QuestionType,
    build_company_registry,
)


def _registries() -> CanonicalRegistries:
    empty = CanonicalRegistry([])
    countries = CanonicalRegistry(
        [CanonicalEntry(canonical_id="country:india", canonical_name="India", aliases=("India",))]
    )
    ports = CanonicalRegistry(
        [
            CanonicalEntry(
                canonical_id="port:mundra", canonical_name="Mundra Port", aliases=("Mundra Port",)
            )
        ]
    )
    commodities = CanonicalRegistry(
        [
            CanonicalEntry(
                canonical_id="commodity:crude_oil",
                canonical_name="Crude Oil",
                aliases=("crude oil",),
            )
        ]
    )
    return CanonicalRegistries(
        countries=countries,
        currencies=empty,
        units=empty,
        incoterms=empty,
        hs_codes=empty,
        commodities=commodities,
        ports=ports,
    )


def _company_node(canonical_id: str, display_name: str) -> GraphNode:
    return GraphNode(
        id=uuid.uuid4(),
        canonical_id=canonical_id,
        node_type="company",
        display_name=display_name,
        aliases_json=[],
        metadata_json={},
        status=GraphNodeStatus.ACTIVE,
    )


def _analyzer() -> QueryAnalyzer:
    companies = build_company_registry(
        [_company_node("company:adani_ports_sez", "Adani Ports SEZ")]
    )
    return QueryAnalyzer(registries=_registries(), companies=companies)


class TestEntityDetection:
    def test_detects_a_port(self) -> None:
        analysis = _analyzer().analyze("Who owns Mundra Port?")
        ports = analysis.entities_by_type("port")
        assert len(ports) == 1
        assert ports[0].canonical_id == "port:mundra"

    def test_detects_a_company_via_graph_derived_registry(self) -> None:
        analysis = _analyzer().analyze("What does Adani Ports SEZ operate?")
        companies = analysis.entities_by_type("company")
        assert len(companies) == 1
        assert companies[0].canonical_id == "company:adani_ports_sez"

    def test_detects_multiple_distinct_entity_types(self) -> None:
        analysis = _analyzer().analyze("Crude Oil shipments from India to Mundra Port")
        types = {e.entity_type for e in analysis.entities}
        assert types == {"commodity", "country", "port"}

    def test_longest_match_wins_over_substring(self) -> None:
        """"Mundra Port" should be detected once as a 2-word span, not
        also matched again as a shorter overlapping span."""
        analysis = _analyzer().analyze("Mundra Port is busy")
        assert len(analysis.entities) == 1
        assert analysis.entities[0].matched_text == "Mundra Port"

    def test_no_entities_in_unrelated_query(self) -> None:
        analysis = _analyzer().analyze("hello there general question")
        assert analysis.entities == []


class TestIntent:
    def test_comparison_intent(self) -> None:
        assert _analyzer().analyze("Compare Brent versus WTI").intent == QueryIntent.COMPARISON

    def test_relationship_intent(self) -> None:
        assert _analyzer().analyze("Who owns Mundra Port?").intent == QueryIntent.RELATIONSHIP

    def test_listing_intent(self) -> None:
        assert _analyzer().analyze("List all ports in India").intent == QueryIntent.LISTING

    def test_definition_intent(self) -> None:
        assert _analyzer().analyze("What is an incoterm?").intent == QueryIntent.DEFINITION

    def test_default_factual_intent(self) -> None:
        assert _analyzer().analyze("Crude oil price today").intent == QueryIntent.FACTUAL

    def test_empty_query_is_unknown(self) -> None:
        assert _analyzer().analyze("   ").intent == QueryIntent.UNKNOWN


class TestQuestionType:
    def test_who_question(self) -> None:
        assert _analyzer().analyze("Who owns Mundra Port?").question_type == QuestionType.WHO

    def test_what_question(self) -> None:
        assert _analyzer().analyze("What is crude oil?").question_type == QuestionType.WHAT

    def test_how_many_question(self) -> None:
        result = _analyzer().analyze("How many ports does Adani operate?")
        assert result.question_type == QuestionType.HOW_MANY

    def test_yes_no_question(self) -> None:
        assert _analyzer().analyze("Is Mundra Port owned by Adani?").question_type == (
            QuestionType.YES_NO
        )

    def test_other_question_type(self) -> None:
        assert _analyzer().analyze("Crude oil prices").question_type == QuestionType.OTHER


class TestTimeRange:
    def test_detects_iso_date(self) -> None:
        result = _analyzer().analyze("Prices on 2026-03-15")
        assert result.time_range is not None
        assert result.time_range.start == datetime(2026, 3, 15, tzinfo=UTC)

    def test_detects_quarter(self) -> None:
        result = _analyzer().analyze("Q1 2026 shipment volumes")
        assert result.time_range is not None
        assert result.time_range.start == datetime(2026, 1, 1, tzinfo=UTC)
        assert result.time_range.end == datetime(2026, 4, 1, tzinfo=UTC)

    def test_detects_bare_year(self) -> None:
        result = _analyzer().analyze("Shipments in 2025")
        assert result.time_range is not None
        assert result.time_range.start == datetime(2025, 1, 1, tzinfo=UTC)
        assert result.time_range.end == datetime(2026, 1, 1, tzinfo=UTC)

    def test_no_time_range_when_absent(self) -> None:
        assert _analyzer().analyze("Who owns Mundra Port?").time_range is None


class TestFilters:
    def test_filters_include_detected_entity_ids(self) -> None:
        result = _analyzer().analyze("Crude Oil shipments from India")
        assert result.filters["commodity_ids"] == ["commodity:crude_oil"]
        assert result.filters["country_ids"] == ["country:india"]

    def test_filters_include_time_range_when_present(self) -> None:
        result = _analyzer().analyze("Shipments in 2025")
        assert "time_range" in result.filters
        assert result.filters["time_range"]["start"] == "2025-01-01T00:00:00+00:00"

    def test_filters_empty_for_bare_query(self) -> None:
        assert _analyzer().analyze("general question").filters == {}
