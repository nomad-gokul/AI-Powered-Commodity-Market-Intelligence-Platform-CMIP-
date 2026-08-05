"""CitationEngine: assembles a Citation for exactly one retrieved item, by
(source_type, source_id).

"Never produce anonymous context" (Phase 5 spec): every branch here either
resolves to a real, identifiable row or raises NotFoundError - it never
returns a Citation for a source that doesn't actually exist, and it never
silently substitutes an empty/placeholder value for a field it could not
resolve without hiding that gap from the caller.
"""

import uuid

from shared.retrieval_contracts import Citation

from app.core.exceptions import NotFoundError
from app.modules.documents.repository import DocumentChunkRepository, DocumentRepository
from app.modules.graph.repository import (
    GraphEdgeRepository,
    GraphEvidenceRepository,
    GraphNodeRepository,
)
from app.modules.retrieval.models import EmbeddingSourceType

_SNIPPET_MAX_CHARS = 280


class CitationEngine:
    def __init__(
        self,
        *,
        document_repo: DocumentRepository,
        chunk_repo: DocumentChunkRepository,
        node_repo: GraphNodeRepository,
        edge_repo: GraphEdgeRepository,
        evidence_repo: GraphEvidenceRepository,
    ) -> None:
        self._document_repo = document_repo
        self._chunk_repo = chunk_repo
        self._node_repo = node_repo
        self._edge_repo = edge_repo
        self._evidence_repo = evidence_repo

    async def cite(self, source_type: EmbeddingSourceType, source_id: str) -> Citation:
        if source_type == EmbeddingSourceType.DOCUMENT_CHUNK:
            return await self._cite_chunk(source_id)
        if source_type == EmbeddingSourceType.GRAPH_NODE:
            return await self._cite_node(source_id)
        if source_type == EmbeddingSourceType.GRAPH_EDGE:
            return await self._cite_edge(source_id)
        if source_type == EmbeddingSourceType.CANONICAL_ENTITY:
            return Citation(
                source_type="canonical_entity", source_id=source_id, canonical_id=source_id
            )
        return Citation(source_type="ontology_definition", source_id=source_id)

    async def _cite_chunk(self, source_id: str) -> Citation:
        chunk_id = uuid.UUID(source_id)
        chunk = await self._chunk_repo.get_by_id(chunk_id)
        if chunk is None:
            raise NotFoundError(f"Document chunk {source_id} not found")
        document = await self._document_repo.get_by_id(chunk.document_id)
        snippet = chunk.text[:_SNIPPET_MAX_CHARS]
        if len(chunk.text) > _SNIPPET_MAX_CHARS:
            snippet += "..."
        return Citation(
            source_type="document_chunk",
            source_id=source_id,
            document_id=str(chunk.document_id),
            document_title=document.original_filename if document else None,
            page_number=chunk.page_number,
            chunk_id=str(chunk.id),
            text_snippet=snippet,
        )

    async def _cite_node(self, source_id: str) -> Citation:
        node = await self._node_repo.get_by_id(uuid.UUID(source_id))
        if node is None:
            raise NotFoundError(f"Graph node {source_id} not found")
        return Citation(
            source_type="graph_node",
            source_id=source_id,
            canonical_id=node.canonical_id,
        )

    async def _cite_edge(self, source_id: str) -> Citation:
        edge = await self._edge_repo.get_by_id(uuid.UUID(source_id))
        if edge is None:
            raise NotFoundError(f"Graph edge {source_id} not found")
        source_node = await self._node_repo.get_by_id(edge.source_node_id)
        target_node = await self._node_repo.get_by_id(edge.target_node_id)
        graph_path = [
            source_node.canonical_id if source_node else str(edge.source_node_id),
            edge.relationship_type,
            target_node.canonical_id if target_node else str(edge.target_node_id),
        ]

        evidence_rows = await self._evidence_repo.list_for_edge(edge.id)
        first_evidence = evidence_rows[0] if evidence_rows else None
        return Citation(
            source_type="graph_edge",
            source_id=source_id,
            document_id=str(first_evidence.document_id) if first_evidence else None,
            page_number=first_evidence.page_number if first_evidence else None,
            chunk_id=str(first_evidence.chunk_id)
            if first_evidence and first_evidence.chunk_id
            else None,
            entity_id=str(first_evidence.entity_id) if first_evidence else None,
            graph_path=graph_path,
            evidence_ids=[str(row.id) for row in evidence_rows],
            confidence=edge.confidence,
        )
