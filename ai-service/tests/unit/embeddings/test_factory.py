"""Unit tests for the config-driven embedding provider factory: correct
provider class per EMBEDDING_PROVIDER, fail-fast on missing key / unknown
model / unknown provider name - mirrors tests/unit/providers/test_factory.py."""

import pytest
from shared.ai_exceptions import ConfigurationError

from ai_service.config.settings import AISettings
from ai_service.embeddings.factory import build_embedding_provider
from ai_service.embeddings.ollama_provider import OllamaEmbeddingProvider
from ai_service.embeddings.openai_provider import OpenAIEmbeddingProvider


def _settings(**overrides: object) -> AISettings:
    return AISettings(_env_file=None, **overrides)  # type: ignore[call-arg,arg-type]


class TestBuildEmbeddingProvider:
    def test_builds_openai_provider_when_configured(self) -> None:
        provider = build_embedding_provider(
            _settings(embedding_provider="openai", openai_api_key="test-key")
        )
        assert isinstance(provider, OpenAIEmbeddingProvider)
        assert provider.dimension == 1536

    def test_builds_ollama_provider_without_requiring_a_key(self) -> None:
        provider = build_embedding_provider(_settings(embedding_provider="ollama"))
        assert isinstance(provider, OllamaEmbeddingProvider)
        assert provider.dimension == 768

    def test_explicit_provider_name_overrides_settings_default(self) -> None:
        provider = build_embedding_provider(
            _settings(embedding_provider="ollama", openai_api_key="key"), provider_name="openai"
        )
        assert isinstance(provider, OpenAIEmbeddingProvider)

    def test_missing_openai_api_key_fails_fast(self) -> None:
        with pytest.raises(ConfigurationError, match="OPENAI_API_KEY"):
            build_embedding_provider(_settings(embedding_provider="openai", openai_api_key=None))

    def test_unknown_model_fails_fast_before_constructing_client(self) -> None:
        with pytest.raises(ConfigurationError, match="Unknown embedding model"):
            build_embedding_provider(
                _settings(
                    embedding_provider="openai",
                    openai_api_key="key",
                    openai_embedding_model="not-a-real-model",
                )
            )

    def test_unknown_provider_name_override_raises(self) -> None:
        with pytest.raises(ConfigurationError, match="Unknown embedding provider"):
            build_embedding_provider(_settings(), provider_name="not-a-real-provider")
