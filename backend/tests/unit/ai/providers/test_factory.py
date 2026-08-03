"""Unit tests for the config-driven provider factory: correct provider
class per LLM_PROVIDER, fail-fast on missing key / unknown model /
unknown provider name."""

import pytest

from app.ai.exceptions import ConfigurationError
from app.ai.providers.claude_provider import ClaudeProvider
from app.ai.providers.factory import build_provider
from app.ai.providers.groq_provider import GroqProvider
from app.ai.providers.ollama_provider import OllamaProvider
from app.ai.providers.openai_provider import OpenAIProvider
from app.core.config import Settings


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg,arg-type]


class TestBuildProvider:
    def test_builds_groq_provider_when_configured(self) -> None:
        provider = build_provider(_settings(llm_provider="groq", groq_api_key="test-key"))
        assert isinstance(provider, GroqProvider)

    def test_builds_claude_provider_when_configured(self) -> None:
        provider = build_provider(_settings(llm_provider="claude", claude_api_key="test-key"))
        assert isinstance(provider, ClaudeProvider)

    def test_builds_openai_provider_when_configured(self) -> None:
        provider = build_provider(_settings(llm_provider="openai", openai_api_key="test-key"))
        assert isinstance(provider, OpenAIProvider)

    def test_builds_ollama_provider_without_requiring_a_key(self) -> None:
        provider = build_provider(_settings(llm_provider="ollama"))
        assert isinstance(provider, OllamaProvider)

    def test_explicit_provider_name_overrides_settings_default(self) -> None:
        provider = build_provider(
            _settings(llm_provider="groq", groq_api_key="a", openai_api_key="b"),
            provider_name="openai",
        )
        assert isinstance(provider, OpenAIProvider)

    def test_missing_groq_api_key_fails_fast(self) -> None:
        with pytest.raises(ConfigurationError, match="GROQ_API_KEY"):
            build_provider(_settings(llm_provider="groq", groq_api_key=None))

    def test_missing_claude_api_key_fails_fast(self) -> None:
        with pytest.raises(ConfigurationError, match="CLAUDE_API_KEY"):
            build_provider(_settings(llm_provider="claude", claude_api_key=None))

    def test_missing_openai_api_key_fails_fast(self) -> None:
        with pytest.raises(ConfigurationError, match="OPENAI_API_KEY"):
            build_provider(_settings(llm_provider="openai", openai_api_key=None))

    def test_unknown_model_fails_fast_before_constructing_client(self) -> None:
        with pytest.raises(ConfigurationError, match="Unknown model"):
            build_provider(
                _settings(llm_provider="groq", groq_api_key="key", groq_model="not-a-real-model")
            )

    def test_unknown_provider_name_override_raises(self) -> None:
        with pytest.raises(ConfigurationError, match="Unknown LLM provider"):
            build_provider(_settings(), provider_name="not-a-real-provider")
