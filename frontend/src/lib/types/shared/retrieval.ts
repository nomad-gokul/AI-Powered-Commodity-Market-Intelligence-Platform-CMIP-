/**
 * Hand-mirrored from shared/shared/retrieval_contracts.py (backend Phase 5).
 * This is a manual sync point, not a generated client — same tradeoff
 * disclosed for EMBEDDING_DIMENSION's 3-way duplication in the backend.
 * Field names and optionality match the Pydantic models exactly so mock
 * payloads shaped against these types look like real API responses.
 */

export type SourceType =
  | "document_chunk"
  | "graph_node"
  | "graph_edge"
  | "canonical_entity"
  | "ontology_definition";

export type RetrievalMethod = "bm25" | "vector" | "graph_expansion" | "hybrid";

export interface RerankSignals {
  vector_similarity?: number | null;
  bm25_score?: number | null;
  graph_distance?: number | null;
  entity_trust?: number | null;
  relationship_confidence?: number | null;
  recency?: number | null;
  document_quality?: number | null;
}

export interface Citation {
  source_type: SourceType;
  source_id: string;
  document_id?: string | null;
  document_title?: string | null;
  page_number?: number | null;
  chunk_id?: string | null;
  text_snippet?: string | null;
  entity_id?: string | null;
  canonical_id?: string | null;
  graph_path: string[];
  evidence_ids: string[];
  confidence?: number | null;
}

export interface RetrievalCandidate {
  source_type: SourceType;
  source_id: string;
  retrieval_method: RetrievalMethod;
  score: number;
  signals: RerankSignals;
  rerank_score?: number | null;
  final_rank?: number | null;
}

export interface RetrievalResultItem {
  candidate: RetrievalCandidate;
  citation: Citation;
}

export interface ContextChunk {
  chunk_id: string;
  document_id: string;
  page_number: number | null;
  text: string;
  citation: Citation;
}

export interface ContextGraphNode {
  node_id: string;
  canonical_id: string;
  node_type: string;
  display_name: string;
  citation: Citation;
}

export interface ContextRelationship {
  edge_id: string;
  source_canonical_id: string;
  target_canonical_id: string;
  relationship_type: string;
  confidence: number;
  citation: Citation;
}

export interface RetrievalContext {
  query: string;
  chunks: ContextChunk[];
  graph_nodes: ContextGraphNode[];
  relationships: ContextRelationship[];
  citations: Citation[];
  total_items: number;
}
