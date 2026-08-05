"""Unit tests for Settings' retrieval configuration (Phase 5): defaults
match the migrated embeddings.embedding_vector column width and the
retrieval-orchestration parameters HybridRetriever reads."""

from app.core.config import Settings


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg,arg-type]


class TestDefaults:
    def test_default_dimension_matches_the_migrated_column_width(self) -> None:
        assert _settings().embedding_dimension == 1536

    def test_default_retrieval_parameters(self) -> None:
        settings = _settings()
        assert settings.retrieval_top_k == 10
        assert settings.retrieval_max_candidates == 200
        assert settings.retrieval_graph_expansion_depth == 2
