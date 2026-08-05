"""ContextBuilder: assembles already-fetched Context* DTOs into one
RetrievalContext.

Pure data assembly - the actual DB queries (chunks, graph traversal,
tables, validation results, canonical entities, ontology definitions) are
backend/app/modules/retrieval/context_service.py's job, since they require
direct knowledge of CMIP's business schema. This builder never touches the
database and never generates a prompt string - "Return only structured
DTOs. No prompt generation here" (Phase 5 spec) - callers decide how, or
whether, to turn a RetrievalContext into a prompt.
"""

from shared.retrieval_contracts import (
    Citation,
    ContextCanonicalEntity,
    ContextChunk,
    ContextGraphNode,
    ContextOntologyDefinition,
    ContextRelationship,
    ContextTable,
    ContextValidationResult,
    RetrievalContext,
)


class ContextBuilder:
    def build(
        self,
        *,
        query: str,
        chunks: list[ContextChunk] | None = None,
        graph_nodes: list[ContextGraphNode] | None = None,
        relationships: list[ContextRelationship] | None = None,
        tables: list[ContextTable] | None = None,
        validation_results: list[ContextValidationResult] | None = None,
        canonical_entities: list[ContextCanonicalEntity] | None = None,
        ontology_definitions: list[ContextOntologyDefinition] | None = None,
    ) -> RetrievalContext:
        chunks = chunks or []
        graph_nodes = graph_nodes or []
        relationships = relationships or []
        tables = tables or []
        validation_results = validation_results or []
        canonical_entities = canonical_entities or []
        ontology_definitions = ontology_definitions or []

        # ContextValidationResult carries no citation of its own - a
        # validation result is about an entity, and that entity is already
        # cited via canonical_entities/chunks/graph_nodes, so including it
        # here would be a duplicate, not a new source.
        citations: list[Citation] = [
            *(item.citation for item in chunks),
            *(item.citation for item in graph_nodes),
            *(item.citation for item in relationships),
            *(item.citation for item in tables),
            *(item.citation for item in canonical_entities),
            *(item.citation for item in ontology_definitions),
        ]

        return RetrievalContext(
            query=query,
            chunks=chunks,
            graph_nodes=graph_nodes,
            relationships=relationships,
            tables=tables,
            validation_results=validation_results,
            canonical_entities=canonical_entities,
            ontology_definitions=ontology_definitions,
            citations=citations,
            total_items=(
                len(chunks)
                + len(graph_nodes)
                + len(relationships)
                + len(tables)
                + len(validation_results)
                + len(canonical_entities)
                + len(ontology_definitions)
            ),
        )


_default_builder = ContextBuilder()


def get_context_builder() -> ContextBuilder:
    return _default_builder
