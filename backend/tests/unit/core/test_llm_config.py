"""Unit tests for Settings' LLM configuration: invalid provider name fails
fast via the Literal type, and production requires an API key for
whichever provider is selected."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg,arg-type]


class TestProviderNameValidation:
    def test_valid_provider_names_are_accepted(self) -> None:
        for name in ("groq", "claude", "openai", "ollama"):
            assert _settings(llm_provider=name).llm_provider == name

    def test_invalid_provider_name_fails_fast_at_construction(self) -> None:
        with pytest.raises(ValidationError):
            _settings(llm_provider="not-a-real-provider")


class TestProductionRequiresApiKey:
    def test_missing_key_in_production_raises(self) -> None:
        with pytest.raises(ValidationError, match="GROQ_API_KEY"):
            _settings(environment="production", llm_provider="groq", groq_api_key=None)

    def test_present_key_in_production_is_accepted(self) -> None:
        settings = _settings(environment="production", llm_provider="groq", groq_api_key="key")
        assert settings.groq_api_key == "key"

    def test_missing_key_in_development_does_not_raise(self) -> None:
        settings = _settings(environment="development", llm_provider="groq", groq_api_key=None)
        assert settings.groq_api_key is None

    def test_ollama_never_requires_a_key_even_in_production(self) -> None:
        settings = _settings(environment="production", llm_provider="ollama")
        assert settings.llm_provider == "ollama"
