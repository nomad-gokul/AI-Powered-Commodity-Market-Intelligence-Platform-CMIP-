"""Unit tests for CitationEngine against mocked repositories: every branch
either resolves a real citation or raises NotFoundError - never an
anonymous/placeholder result."""

import uuid
from unittest.mock import AsyncMock

import pytest

from app.core.exceptions import NotFoundError
from app.modules.documents.models import Document, DocumentChunk, StorageProviderKind
from app.modules.graph.models import GraphEdge, GraphEvidence, GraphNode, GraphNodeStatus
from app.modules.retrieval.citation_engine import CitationEngine
from app.modules.retrieval.models import EmbeddingSourceType

pytestmark = pytest.mark.asyncio


def _chunk(chunk_id: uuid.UUID, document_id: uuid.UUID, *, text: str = "hello") -> DocumentChunk:
    return DocumentChunk(
        id=chunk_id,
        document_id=document_id,
        chunk_index=0,
        page_number=3,
        text=text,
        token_count=10,
        metadata_json={},
    )


def _document(document_id: uuid.UUID) -> Document:
    return Document(
        id=document_id,
        uploaded_by=uuid.uuid4(),
        filename="a.pdf",
        original_filename="Platts Report.pdf",
        extension="pdf",
        mime_type="application/pdf",
        file_size=100,
        sha256_hash="x" * 64,
        storage_provider=StorageProviderKind.LOCAL,
        storage_key="k",
    )


def _node(node_id: uuid.UUID, canonical_id: str) -> GraphNode:
    return GraphNode(
        id=node_id,
        canonical_id=canonical_id,
        node_type="company",
        display_name=canonical_id,
        aliases_json=[],
        metadata_json={},
        status=GraphNodeStatus.ACTIVE,
    )


def _edge(edge_id: uuid.UUID, source_id: uuid.UUID, target_id: uuid.UUID) -> GraphEdge:
    return GraphEdge(
        id=edge_id,
        source_node_id=source_id,
        target_node_id=target_id,
        relationship_type="owns",
        confidence=0.85,
        evidence_count=1,
        provenance_json={},
    )


def _make_engine(
    *,
    document=None,
    chunk=None,
    node=None,
    edge=None,
    source_node=None,
    target_node=None,
    evidence=None,
) -> CitationEngine:
    document_repo = AsyncMock()
    document_repo.get_by_id.return_value = document
    chunk_repo = AsyncMock()
    chunk_repo.get_by_id.return_value = chunk
    node_repo = AsyncMock()
    node_repo.get_by_id.side_effect = [node] if node is not None else [source_node, target_node]
    edge_repo = AsyncMock()
    edge_repo.get_by_id.return_value = edge
    evidence_repo = AsyncMock()
    evidence_repo.list_for_edge.return_value = evidence or []
    return CitationEngine(
        document_repo=document_repo,
        chunk_repo=chunk_repo,
        node_repo=node_repo,
        edge_repo=edge_repo,
        evidence_repo=evidence_repo,
    )


class TestCiteDocumentChunk:
    async def test_returns_full_citation_with_document_title_and_snippet(self) -> None:
        chunk_id, document_id = uuid.uuid4(), uuid.uuid4()
        engine = _make_engine(
            document=_document(document_id), chunk=_chunk(chunk_id, document_id)
        )

        citation = await engine.cite(EmbeddingSourceType.DOCUMENT_CHUNK, str(chunk_id))

        assert citation.document_id == str(document_id)
        assert citation.document_title == "Platts Report.pdf"
        assert citation.page_number == 3
        assert citation.text_snippet == "hello"

    async def test_truncates_long_text_with_ellipsis(self) -> None:
        chunk_id, document_id = uuid.uuid4(), uuid.uuid4()
        long_text = "x" * 500
        engine = _make_engine(
            document=_document(document_id), chunk=_chunk(chunk_id, document_id, text=long_text)
        )

        citation = await engine.cite(EmbeddingSourceType.DOCUMENT_CHUNK, str(chunk_id))

        assert citation.text_snippet is not None
        assert citation.text_snippet.endswith("...")
        assert len(citation.text_snippet) == 283

    async def test_missing_chunk_raises_not_found(self) -> None:
        engine = _make_engine(chunk=None)
        with pytest.raises(NotFoundError):
            await engine.cite(EmbeddingSourceType.DOCUMENT_CHUNK, str(uuid.uuid4()))


class TestCiteGraphNode:
    async def test_returns_canonical_id(self) -> None:
        node_id = uuid.uuid4()
        engine = _make_engine(node=_node(node_id, "company:adani_ports_sez"))

        citation = await engine.cite(EmbeddingSourceType.GRAPH_NODE, str(node_id))

        assert citation.canonical_id == "company:adani_ports_sez"

    async def test_missing_node_raises_not_found(self) -> None:
        engine = _make_engine(node=None)
        with pytest.raises(NotFoundError):
            await engine.cite(EmbeddingSourceType.GRAPH_NODE, str(uuid.uuid4()))


class TestCiteGraphEdge:
    async def test_returns_graph_path_and_evidence(self) -> None:
        edge_id, source_id, target_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        document_id, chunk_id, entity_id, extraction_run_id = (
            uuid.uuid4(),
            uuid.uuid4(),
            uuid.uuid4(),
            uuid.uuid4(),
        )
        evidence = GraphEvidence(
            id=uuid.uuid4(),
            edge_id=edge_id,
            document_id=document_id,
            extraction_run_id=extraction_run_id,
            entity_id=entity_id,
            page_number=2,
            chunk_id=chunk_id,
            prompt_hash="h" * 64,
        )
        engine = _make_engine(
            edge=_edge(edge_id, source_id, target_id),
            source_node=_node(source_id, "company:adani_ports_sez"),
            target_node=_node(target_id, "port:mundra"),
            evidence=[evidence],
        )

        citation = await engine.cite(EmbeddingSourceType.GRAPH_EDGE, str(edge_id))

        assert citation.graph_path == ["company:adani_ports_sez", "owns", "port:mundra"]
        assert citation.document_id == str(document_id)
        assert citation.confidence == 0.85
        assert citation.evidence_ids == [str(evidence.id)]

    async def test_missing_edge_raises_not_found(self) -> None:
        engine = _make_engine(edge=None, source_node=None, target_node=None)
        with pytest.raises(NotFoundError):
            await engine.cite(EmbeddingSourceType.GRAPH_EDGE, str(uuid.uuid4()))

    async def test_edge_without_evidence_still_returns_a_citation(self) -> None:
        edge_id, source_id, target_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        engine = _make_engine(
            edge=_edge(edge_id, source_id, target_id),
            source_node=_node(source_id, "company:a"),
            target_node=_node(target_id, "port:b"),
            evidence=[],
        )

        citation = await engine.cite(EmbeddingSourceType.GRAPH_EDGE, str(edge_id))

        assert citation.document_id is None
        assert citation.evidence_ids == []


class TestCiteCanonicalEntityAndOntology:
    async def test_canonical_entity_citation_uses_source_id_as_canonical_id(self) -> None:
        engine = _make_engine()
        citation = await engine.cite(
            EmbeddingSourceType.CANONICAL_ENTITY, "company:adani_ports_sez"
        )
        assert citation.canonical_id == "company:adani_ports_sez"
        assert citation.source_type == "canonical_entity"

    async def test_ontology_definition_citation(self) -> None:
        engine = _make_engine()
        citation = await engine.cite(EmbeddingSourceType.ONTOLOGY_DEFINITION, "company")
        assert citation.source_type == "ontology_definition"
        assert citation.source_id == "company"
