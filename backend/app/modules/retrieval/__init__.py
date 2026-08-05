"""Phase 5: Knowledge Retrieval Platform.

Combines document chunks, the knowledge graph, canonical entities,
ontology, and validation results into one hybrid (BM25 + vector + graph
expansion) retrieval pipeline. Owns the DB-backed orchestration
(embeddings/retrieval_runs/retrieval_results tables, repositories,
HybridRetriever, QueryAnalyzer, CitationEngine) - the stateless AI
infrastructure it calls into (EmbeddingProvider, RerankerService,
ContextBuilder) lives in ai-service. See docs/ARCHITECTURE.md's Phase 5
section for the full split rationale.
"""
