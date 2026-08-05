"""Reranking (Phase 5: Knowledge Retrieval Platform).

RerankerService is pure scoring over already-computed signals - it never
touches the database or CMIP's business schema directly. Query analysis,
BM25/vector/graph-expansion orchestration, and citation assembly live in
backend/app/modules/retrieval instead, since they need direct knowledge of
the app's business data - see docs/ARCHITECTURE.md's Phase 5 section."""
