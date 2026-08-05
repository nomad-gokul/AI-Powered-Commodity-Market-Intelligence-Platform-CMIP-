"""Retrieval, reranking, and context-assembly DTOs shared between backend's
DB-backed hybrid-retrieval orchestration and ai-service's stateless
RerankerService/ContextBuilder.

Mirrors the ai_contracts.py split: pure data here, consumed directly by
backend/app/modules/retrieval (which owns the DB queries, the knowledge
graph, and the canonical registry) and by ai_service.retrieval.reranker /
ai_service.context.builder (which operate purely on already-populated
instances of these DTOs - they never touch the database or any of CMIP's
business schema directly).
"""

from typing import Literal

from pydantic import BaseModel, Field

SourceType = Literal[
    "document_chunk", "graph_node", "graph_edge", "canonical_entity", "ontology_definition"
]
RetrievalMethod = Literal["bm25", "vector", "graph_expansion", "hybrid"]


class RerankSignals(BaseModel):
    """Raw scoring inputs RerankerService combines into one final score.
    Every field is optional because not every candidate carries every
    signal - a BM25-only chunk hit has no relationship_confidence, a
    graph-expansion edge has no bm25_score."""

    vector_similarity: float | None = None
    bm25_score: float | None = None
    graph_distance: int | None = None
    entity_trust: float | None = None
    relationship_confidence: float | None = None
    recency: float | None = None
    document_quality: float | None = None


class Citation(BaseModel):
    """Provenance for exactly one retrieved item. Every RetrievalResultItem
    and every Context* DTO carries one of these - retrieval must never
    produce anonymous context."""

    source_type: SourceType
    source_id: str
    document_id: str | None = None
    document_title: str | None = None
    page_number: int | None = None
    chunk_id: str | None = None
    text_snippet: str | None = None
    entity_id: str | None = None
    canonical_id: str | None = None
    graph_path: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: float | None = None


class RetrievalCandidate(BaseModel):
    source_type: SourceType
    source_id: str
    retrieval_method: RetrievalMethod
    score: float
    signals: RerankSignals = Field(default_factory=RerankSignals)
    rerank_score: float | None = None
    final_rank: int | None = None


class RetrievalResultItem(BaseModel):
    candidate: RetrievalCandidate
    citation: Citation


class ContextChunk(BaseModel):
    chunk_id: str
    document_id: str
    page_number: int | None
    text: str
    citation: Citation


class ContextGraphNode(BaseModel):
    node_id: str
    canonical_id: str
    node_type: str
    display_name: str
    citation: Citation


class ContextRelationship(BaseModel):
    edge_id: str
    source_canonical_id: str
    target_canonical_id: str
    relationship_type: str
    confidence: float
    citation: Citation


class ContextTable(BaseModel):
    table_id: str
    document_id: str
    page_number: int
    title: str | None
    row_count: int
    column_count: int
    citation: Citation


class ContextValidationResult(BaseModel):
    validation_result_id: str
    entity_id: str | None
    validation_rule: str
    severity: str
    passed: bool
    message: str


class ContextCanonicalEntity(BaseModel):
    canonical_id: str
    canonical_name: str
    entity_type: str
    aliases: list[str] = Field(default_factory=list)
    citation: Citation


class ContextOntologyDefinition(BaseModel):
    entity_type: str
    description: str
    parent_type: str | None = None
    citation: Citation


class RetrievalContext(BaseModel):
    """The single structured object ContextBuilder assembles - the
    retrieval platform's entire output contract for downstream AI
    capabilities (Executive Commentary, Forecasting, AI Copilot). Never a
    prompt string - callers own how, or whether, to turn this into one."""

    query: str
    chunks: list[ContextChunk] = Field(default_factory=list)
    graph_nodes: list[ContextGraphNode] = Field(default_factory=list)
    relationships: list[ContextRelationship] = Field(default_factory=list)
    tables: list[ContextTable] = Field(default_factory=list)
    validation_results: list[ContextValidationResult] = Field(default_factory=list)
    canonical_entities: list[ContextCanonicalEntity] = Field(default_factory=list)
    ontology_definitions: list[ContextOntologyDefinition] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    total_items: int = 0


__all__ = [
    "Citation",
    "ContextCanonicalEntity",
    "ContextChunk",
    "ContextGraphNode",
    "ContextOntologyDefinition",
    "ContextRelationship",
    "ContextTable",
    "ContextValidationResult",
    "RerankSignals",
    "RetrievalCandidate",
    "RetrievalContext",
    "RetrievalMethod",
    "RetrievalResultItem",
    "SourceType",
]
