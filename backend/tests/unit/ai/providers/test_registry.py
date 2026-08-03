"""Unit tests for ProviderRegistry: model lookup, alias resolution, and
cost estimation."""

import pytest

from app.ai.exceptions import ConfigurationError
from app.ai.providers.base import LLMUsage, ProviderCapabilities
from app.ai.providers.models import ProviderModelInfo
from app.ai.providers.registry import ProviderRegistry, get_provider_registry


class TestGetModelInfo:
    def test_returns_known_model(self) -> None:
        registry = get_provider_registry()
        info = registry.get_model_info("groq", "llama-3.3-70b-versatile")
        assert info.provider == "groq"
        assert info.context_window > 0

    def test_resolves_alias(self) -> None:
        registry = get_provider_registry()
        by_alias = registry.get_model_info("groq", "llama-3.1-8b")
        by_canonical = registry.get_model_info("groq", "llama-3.1-8b-instant")
        assert by_alias.model_id == by_canonical.model_id

    def test_unknown_model_raises_configuration_error_with_known_models_listed(self) -> None:
        registry = get_provider_registry()
        with pytest.raises(ConfigurationError) as exc_info:
            registry.get_model_info("groq", "not-a-real-model")
        assert "not-a-real-model" in str(exc_info.value)
        assert exc_info.value.details["known_models"]

    def test_unknown_provider_raises_configuration_error(self) -> None:
        registry = get_provider_registry()
        with pytest.raises(ConfigurationError):
            registry.get_model_info("not-a-real-provider", "anything")


class TestDefaultModel:
    def test_returns_default_for_each_known_provider(self) -> None:
        registry = get_provider_registry()
        for provider in ("groq", "claude", "openai", "ollama"):
            default = registry.default_model(provider)
            assert registry.get_model_info(provider, default) is not None

    def test_unknown_provider_raises(self) -> None:
        with pytest.raises(ConfigurationError):
            get_provider_registry().default_model("not-a-real-provider")


class TestListModels:
    def test_returns_only_models_for_requested_provider(self) -> None:
        registry = get_provider_registry()
        models = registry.list_models("groq")
        assert models
        assert all(m.provider == "groq" for m in models)

    def test_does_not_duplicate_aliased_models(self) -> None:
        registry = get_provider_registry()
        model_ids = [m.model_id for m in registry.list_models("groq")]
        assert len(model_ids) == len(set(model_ids))


class TestEstimateCost:
    def test_computes_cost_from_usage_and_pricing(self) -> None:
        registry = ProviderRegistry()
        usage = LLMUsage(
            prompt_tokens=1_000_000, completion_tokens=1_000_000, total_tokens=2_000_000
        )
        cost = registry.estimate_cost_usd("groq", "llama-3.3-70b-versatile", usage)
        assert cost == pytest.approx(0.59 + 0.79)

    def test_returns_none_for_model_with_no_pricing(self) -> None:
        registry = ProviderRegistry()
        usage = LLMUsage(prompt_tokens=100, completion_tokens=100, total_tokens=200)
        assert registry.estimate_cost_usd("ollama", "llama3.1", usage) is None

    def test_zero_usage_returns_zero_cost(self) -> None:
        registry = ProviderRegistry()
        cost = registry.estimate_cost_usd("groq", "llama-3.3-70b-versatile", LLMUsage())
        assert cost == 0.0

    def test_asymmetric_pricing_with_only_output_price_unknown_returns_none(self) -> None:
        """A model with an input price but no known output price is still
        an incomplete cost estimate - must degrade to None, not silently
        compute cost from input tokens alone."""
        info = ProviderModelInfo(
            provider="synthetic",
            model_id="half-priced",
            context_window=1000,
            max_output_tokens=100,
            capabilities=ProviderCapabilities(),
            input_price_per_million_tokens=1.0,
            output_price_per_million_tokens=None,
        )
        registry = ProviderRegistry(models=(info,))
        usage = LLMUsage(prompt_tokens=1000, completion_tokens=1000, total_tokens=2000)
        assert registry.estimate_cost_usd("synthetic", "half-priced", usage) is None

    def test_unregistered_provider_or_model_returns_none_instead_of_raising(self) -> None:
        """Cost estimation feeds observability bookkeeping AFTER a real
        call already succeeded - an unregistered provider/model must
        degrade to "unknown cost", never raise and fail the caller."""
        registry = ProviderRegistry()
        assert registry.estimate_cost_usd("not-a-real-provider", "x", LLMUsage()) is None
