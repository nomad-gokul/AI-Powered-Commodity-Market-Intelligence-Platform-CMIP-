"""Unit tests for EmbeddingModelRegistry: model lookup and fail-fast
behavior for unknown providers/models."""

import pytest
from shared.ai_exceptions import ConfigurationError

from ai_service.embeddings.models import EmbeddingModelInfo
from ai_service.embeddings.registry import EmbeddingModelRegistry, get_embedding_model_registry


class TestGetModelInfo:
    def test_returns_known_model(self) -> None:
        registry = get_embedding_model_registry()
        info = registry.get_model_info("openai", "text-embedding-3-small")
        assert info.provider == "openai"
        assert info.dimension == 1536

    def test_unknown_model_raises_configuration_error_with_known_models_listed(self) -> None:
        registry = get_embedding_model_registry()
        with pytest.raises(ConfigurationError) as exc_info:
            registry.get_model_info("openai", "not-a-real-model")
        assert "not-a-real-model" in str(exc_info.value)
        assert exc_info.value.details["known_models"]

    def test_unknown_provider_raises_configuration_error(self) -> None:
        registry = get_embedding_model_registry()
        with pytest.raises(ConfigurationError):
            registry.get_model_info("not-a-real-provider", "anything")


class TestDefaultModel:
    def test_returns_default_for_each_known_provider(self) -> None:
        registry = get_embedding_model_registry()
        for provider in ("openai", "ollama"):
            default = registry.default_model(provider)
            assert registry.get_model_info(provider, default) is not None

    def test_unknown_provider_raises(self) -> None:
        with pytest.raises(ConfigurationError):
            get_embedding_model_registry().default_model("not-a-real-provider")


class TestListModels:
    def test_returns_only_models_for_requested_provider(self) -> None:
        registry = get_embedding_model_registry()
        models = registry.list_models("openai")
        assert models
        assert all(m.provider == "openai" for m in models)

    def test_does_not_duplicate_aliased_models(self) -> None:
        info = EmbeddingModelInfo(
            provider="synthetic",
            model_id="model-a",
            dimension=8,
            max_input_tokens=100,
            price_per_million_tokens=None,
            aliases=("model-a-alias",),
        )
        registry = EmbeddingModelRegistry(models=(info,))
        model_ids = [m.model_id for m in registry.list_models("synthetic")]
        assert model_ids == ["model-a"]
