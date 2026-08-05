"""Unit tests for ContextService: hydrates real Context* DTOs for each
candidate source_type against mocked repositories/CitationEngine, using
the REAL ai_service ContextBuilder for final assembly (pure, cheap, worth
exercising for real rather than mocking away)."""

import uuid
from unittest.mock import AsyncMock

import pytest
from ai_service.context.builder import ContextBuilder
from shared.retrieval_contracts import Citation, RetrievalCandidate

from app.modules.documents.models import DocumentChunk
from app.modules.extraction.trust.normalization.canonical_registry import (
    CanonicalEntry,
    CanonicalRegistry,
)
from app.modules.extraction.trust.normalization.loader import CanonicalRegistries
from app.modules.graph.models import GraphEdge, GraphNode, GraphNodeStatus, OntologyType
from app.modules.retrieval.context_service import ContextService

pytestmark = pytest.mark.asyncio


def _candidate(source_type: str, source_id: str) -> RetrievalCandidate:
    return RetrievalCandidate(
        source_type=source_type,  # type: ignore[arg-type]
        source_id=source_id,
        retrieval_method="hybrid",
        score=1.0,
    )


def _citation(source_type: str, source_id: str) -> Citation:
    return Citation(source_type=source_type, source_id=source_id)  # type: ignore[arg-type]


def _empty_registries() -> CanonicalRegistries:
    empty = CanonicalRegistry([])
    return CanonicalRegistries(
        countries=empty, currencies=empty, units=empty, incoterms=empty,
        hs_codes=empty, commodities=empty, ports=empty,
    )


def _service(
    *, chunk=None, node=None, edge=None, source_node=None, target_node=None, ontology=None,
    companies: CanonicalRegistry | None = None,
) -> ContextService:
    chunk_repo = AsyncMock()
    chunk_repo.get_by_id.return_value = chunk
    node_repo = AsyncMock()
    node_repo.get_by_id.side_effect = (
        [node] if node is not None else [source_node, target_node]
    )
    edge_repo = AsyncMock()
    edge_repo.get_by_id.return_value = edge
    ontology_repo = AsyncMock()
    ontology_repo.get_by_entity_type.return_value = ontology
    citation_engine = AsyncMock()
    citation_engine.cite.side_effect = lambda source_type, source_id: _citation(
        source_type.value, source_id
    )
    return ContextService(
        chunk_repo=chunk_repo,
        node_repo=node_repo,
        edge_repo=edge_repo,
        ontology_repo=ontology_repo,
        citation_engine=citation_engine,
        context_builder=ContextBuilder(),
        registries=_empty_registries(),
        companies=companies or CanonicalRegistry([]),
    )


class TestBuildContext:
    async def test_hydrates_document_chunk(self) -> None:
        chunk_id, document_id = uuid.uuid4(), uuid.uuid4()
        chunk = DocumentChunk(
            id=chunk_id, document_id=document_id, chunk_index=0, page_number=1,
            text="hello world", token_count=2, metadata_json={},
        )
        service = _service(chunk=chunk)

        context = await service.build_context(
            "query", [_candidate("document_chunk", str(chunk_id))]
        )

        assert len(context.chunks) == 1
        assert context.chunks[0].text == "hello world"
        assert context.total_items == 1

    async def test_hydrates_graph_node(self) -> None:
        node_id = uuid.uuid4()
        node = GraphNode(
            id=node_id, canonical_id="port:mundra", node_type="port", display_name="Mundra Port",
            aliases_json=[], metadata_json={}, status=GraphNodeStatus.ACTIVE,
        )
        service = _service(node=node)

        context = await service.build_context("query", [_candidate("graph_node", str(node_id))])

        assert len(context.graph_nodes) == 1
        assert context.graph_nodes[0].canonical_id == "port:mundra"

    async def test_hydrates_graph_edge_with_resolved_endpoints(self) -> None:
        edge_id, source_id, target_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        edge = GraphEdge(
            id=edge_id, source_node_id=source_id, target_node_id=target_id,
            relationship_type="owns", confidence=0.9, evidence_count=1, provenance_json={},
        )
        source_node = GraphNode(
            id=source_id, canonical_id="company:a", node_type="company", display_name="A",
            aliases_json=[], metadata_json={}, status=GraphNodeStatus.ACTIVE,
        )
        target_node = GraphNode(
            id=target_id, canonical_id="port:b", node_type="port", display_name="B",
            aliases_json=[], metadata_json={}, status=GraphNodeStatus.ACTIVE,
        )
        service = _service(edge=edge, source_node=source_node, target_node=target_node)

        context = await service.build_context("query", [_candidate("graph_edge", str(edge_id))])

        assert len(context.relationships) == 1
        assert context.relationships[0].source_canonical_id == "company:a"
        assert context.relationships[0].target_canonical_id == "port:b"

    async def test_hydrates_canonical_entity_with_resolved_name(self) -> None:
        companies = CanonicalRegistry(
            [CanonicalEntry(canonical_id="company:a", canonical_name="Company A", aliases=("A",))]
        )
        service = _service(companies=companies)

        context = await service.build_context(
            "query", [_candidate("canonical_entity", "company:a")]
        )

        assert len(context.canonical_entities) == 1
        assert context.canonical_entities[0].canonical_name == "Company A"
        assert context.canonical_entities[0].entity_type == "company"

    async def test_canonical_entity_falls_back_to_id_when_unresolvable(self) -> None:
        service = _service()

        context = await service.build_context(
            "query", [_candidate("canonical_entity", "company:unknown")]
        )

        assert context.canonical_entities[0].canonical_name == "company:unknown"

    async def test_hydrates_ontology_definition(self) -> None:
        ontology = OntologyType(
            id=uuid.uuid4(), entity_type="company", description="A commercial entity.",
            parent_type=None, metadata_json={},
        )
        service = _service(ontology=ontology)

        context = await service.build_context(
            "query", [_candidate("ontology_definition", "company")]
        )

        assert len(context.ontology_definitions) == 1
        assert context.ontology_definitions[0].description == "A commercial entity."

    async def test_missing_row_is_skipped_not_errored(self) -> None:
        service = _service(chunk=None)

        context = await service.build_context(
            "query", [_candidate("document_chunk", str(uuid.uuid4()))]
        )

        assert context.chunks == []
        assert context.total_items == 0

    async def test_combines_multiple_source_types(self) -> None:
        chunk_id, document_id = uuid.uuid4(), uuid.uuid4()
        chunk = DocumentChunk(
            id=chunk_id, document_id=document_id, chunk_index=0, page_number=1,
            text="hello", token_count=1, metadata_json={},
        )
        node_id = uuid.uuid4()
        node = GraphNode(
            id=node_id, canonical_id="port:mundra", node_type="port", display_name="Mundra Port",
            aliases_json=[], metadata_json={}, status=GraphNodeStatus.ACTIVE,
        )
        chunk_repo = AsyncMock()
        chunk_repo.get_by_id.return_value = chunk
        node_repo = AsyncMock()
        node_repo.get_by_id.return_value = node
        edge_repo = AsyncMock()
        ontology_repo = AsyncMock()
        citation_engine = AsyncMock()
        citation_engine.cite.side_effect = lambda source_type, source_id: _citation(
            source_type.value, source_id
        )
        service = ContextService(
            chunk_repo=chunk_repo, node_repo=node_repo, edge_repo=edge_repo,
            ontology_repo=ontology_repo, citation_engine=citation_engine,
            context_builder=ContextBuilder(), registries=_empty_registries(),
            companies=CanonicalRegistry([]),
        )

        context = await service.build_context(
            "query",
            [_candidate("document_chunk", str(chunk_id)), _candidate("graph_node", str(node_id))],
        )

        assert context.total_items == 2
        assert len(context.citations) == 2
