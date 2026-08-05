"""ContextService: hydrates full domain objects for a HybridRetriever
result's ranked candidates, and calls ai-service's ContextBuilder to
assemble them into one RetrievalContext.

This is the DB-facing half of context assembly - fetching chunks/graph
nodes/edges/ontology definitions from their real repositories, pairing
each with a CitationEngine citation. ai_service.context.builder.
ContextBuilder itself is pure assembly over the DTOs this service
produces; it never touches the database.

Disclosed scope decision: `tables` and `validation_results` are never
populated here - both would need a further join (chunk -> extracted
entity -> table/validation_result) that isn't wired in this phase; they
stay empty lists, which ContextBuilder already handles as "no items of
this kind," never a fabricated result.
"""

import uuid

from ai_service.context.builder import ContextBuilder
from shared.retrieval_contracts import (
    Citation,
    ContextCanonicalEntity,
    ContextChunk,
    ContextGraphNode,
    ContextOntologyDefinition,
    ContextRelationship,
    RetrievalCandidate,
    RetrievalContext,
)

from app.core.metrics import retrieval_context_size
from app.modules.documents.repository import DocumentChunkRepository
from app.modules.extraction.trust.normalization.canonical_registry import CanonicalRegistry
from app.modules.extraction.trust.normalization.loader import CanonicalRegistries
from app.modules.graph.repository import (
    GraphEdgeRepository,
    GraphNodeRepository,
    OntologyTypeRepository,
)
from app.modules.retrieval.citation_engine import CitationEngine
from app.modules.retrieval.models import EmbeddingSourceType


class ContextService:
    def __init__(
        self,
        *,
        chunk_repo: DocumentChunkRepository,
        node_repo: GraphNodeRepository,
        edge_repo: GraphEdgeRepository,
        ontology_repo: OntologyTypeRepository,
        citation_engine: CitationEngine,
        context_builder: ContextBuilder,
        registries: CanonicalRegistries,
        companies: CanonicalRegistry,
    ) -> None:
        self._chunk_repo = chunk_repo
        self._node_repo = node_repo
        self._edge_repo = edge_repo
        self._ontology_repo = ontology_repo
        self._citation_engine = citation_engine
        self._context_builder = context_builder
        self._name_sources: tuple[CanonicalRegistry, ...] = (
            companies,
            registries.countries,
            registries.ports,
            registries.commodities,
        )

    async def build_context(
        self, query: str, candidates: list[RetrievalCandidate]
    ) -> RetrievalContext:
        chunks: list[ContextChunk] = []
        graph_nodes: list[ContextGraphNode] = []
        relationships: list[ContextRelationship] = []
        canonical_entities: list[ContextCanonicalEntity] = []
        ontology_definitions: list[ContextOntologyDefinition] = []

        for candidate in candidates:
            source_type = EmbeddingSourceType(candidate.source_type)
            citation = await self._citation_engine.cite(source_type, candidate.source_id)

            if source_type == EmbeddingSourceType.DOCUMENT_CHUNK:
                chunk = await self._chunk_repo.get_by_id(uuid.UUID(candidate.source_id))
                if chunk is None:
                    continue
                chunks.append(
                    ContextChunk(
                        chunk_id=str(chunk.id),
                        document_id=str(chunk.document_id),
                        page_number=chunk.page_number,
                        text=chunk.text,
                        citation=citation,
                    )
                )
            elif source_type == EmbeddingSourceType.GRAPH_NODE:
                node = await self._node_repo.get_by_id(uuid.UUID(candidate.source_id))
                if node is None:
                    continue
                graph_nodes.append(
                    ContextGraphNode(
                        node_id=str(node.id),
                        canonical_id=node.canonical_id,
                        node_type=node.node_type,
                        display_name=node.display_name,
                        citation=citation,
                    )
                )
            elif source_type == EmbeddingSourceType.GRAPH_EDGE:
                edge = await self._edge_repo.get_by_id(uuid.UUID(candidate.source_id))
                if edge is None:
                    continue
                source_node = await self._node_repo.get_by_id(edge.source_node_id)
                target_node = await self._node_repo.get_by_id(edge.target_node_id)
                relationships.append(
                    ContextRelationship(
                        edge_id=str(edge.id),
                        source_canonical_id=(
                            source_node.canonical_id
                            if source_node
                            else str(edge.source_node_id)
                        ),
                        target_canonical_id=(
                            target_node.canonical_id
                            if target_node
                            else str(edge.target_node_id)
                        ),
                        relationship_type=edge.relationship_type,
                        confidence=edge.confidence,
                        citation=citation,
                    )
                )
            elif source_type == EmbeddingSourceType.CANONICAL_ENTITY:
                canonical_entities.append(
                    self._build_canonical_entity(candidate.source_id, citation)
                )
            else:
                ontology_type = await self._ontology_repo.get_by_entity_type(candidate.source_id)
                if ontology_type is None:
                    continue
                ontology_definitions.append(
                    ContextOntologyDefinition(
                        entity_type=ontology_type.entity_type,
                        description=ontology_type.description,
                        parent_type=ontology_type.parent_type,
                        citation=citation,
                    )
                )

        context = self._context_builder.build(
            query=query,
            chunks=chunks,
            graph_nodes=graph_nodes,
            relationships=relationships,
            canonical_entities=canonical_entities,
            ontology_definitions=ontology_definitions,
        )
        retrieval_context_size.observe(context.total_items)
        return context

    def _build_canonical_entity(
        self, canonical_id: str, citation: Citation
    ) -> ContextCanonicalEntity:
        for source in self._name_sources:
            match = source.resolve_by_id(canonical_id)
            if match is not None:
                entity_type = canonical_id.split(":", 1)[0] if ":" in canonical_id else "unknown"
                return ContextCanonicalEntity(
                    canonical_id=canonical_id,
                    canonical_name=match.canonical_name,
                    entity_type=entity_type,
                    aliases=[],
                    citation=citation,
                )
        entity_type = canonical_id.split(":", 1)[0] if ":" in canonical_id else "unknown"
        return ContextCanonicalEntity(
            canonical_id=canonical_id,
            canonical_name=canonical_id,
            entity_type=entity_type,
            aliases=[],
            citation=citation,
        )
