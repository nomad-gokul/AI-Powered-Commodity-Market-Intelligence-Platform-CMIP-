"""Embedding provider abstraction (Phase 5: Knowledge Retrieval Platform).

Mirrors ai_service.providers exactly: EmbeddingProvider is the ABC every
vendor integration implements, backend/app/modules/retrieval's
EmbeddingService is the only caller, and adding a new provider means
writing one new class in this package."""
