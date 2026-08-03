"""ProviderRegistry: the single source of truth for "what models exist".

A typo'd model name (GROQ_MODEL=llama-3.3-70b-versatil) fails fast here,
at provider-construction time, with a clear ConfigurationError - not three
requests later as an opaque 400 from the vendor API.
"""

from app.ai.exceptions import ConfigurationError
from app.ai.providers.base import LLMUsage
from app.ai.providers.models import DEFAULT_MODEL_BY_PROVIDER, MODELS, ProviderModelInfo


class ProviderRegistry:
    def __init__(self, models: tuple[ProviderModelInfo, ...] = MODELS) -> None:
        self._by_key: dict[tuple[str, str], ProviderModelInfo] = {}
        for info in models:
            self._by_key[(info.provider, info.model_id)] = info
            for alias in info.aliases:
                self._by_key[(info.provider, alias)] = info

    def get_model_info(self, provider: str, model_id: str) -> ProviderModelInfo:
        try:
            return self._by_key[(provider, model_id)]
        except KeyError:
            known = sorted({key[1] for key in self._by_key if key[0] == provider})
            raise ConfigurationError(
                f"Unknown model {model_id!r} for provider {provider!r}. "
                f"Known models: {known or '(none registered)'}",
                details={"provider": provider, "model": model_id, "known_models": known},
            ) from None

    def default_model(self, provider: str) -> str:
        try:
            return DEFAULT_MODEL_BY_PROVIDER[provider]
        except KeyError:
            raise ConfigurationError(
                f"No default model configured for provider {provider!r}"
            ) from None

    def list_models(self, provider: str) -> list[ProviderModelInfo]:
        seen: set[str] = set()
        result: list[ProviderModelInfo] = []
        for (prov, _key), info in self._by_key.items():
            if prov == provider and info.model_id not in seen:
                seen.add(info.model_id)
                result.append(info)
        return result

    def estimate_cost_usd(self, provider: str, model_id: str, usage: LLMUsage) -> float | None:
        """Return a rough USD estimate for `usage`, or None if the model has
        no known per-token pricing (e.g. self-hosted Ollama) OR isn't
        registered at all. Deliberately never raises: this feeds
        observability bookkeeping in LLMClient, called AFTER a generation
        has already succeeded - a cost-estimation gap must never fail a
        call that has already gotten its real result back to the caller.
        """
        try:
            info = self.get_model_info(provider, model_id)
        except ConfigurationError:
            return None
        if info.input_price_per_million_tokens is None:
            return None
        if info.output_price_per_million_tokens is None:
            return None

        input_cost = (usage.prompt_tokens / 1_000_000) * info.input_price_per_million_tokens
        output_cost = (usage.completion_tokens / 1_000_000) * info.output_price_per_million_tokens
        return input_cost + output_cost


_default_registry = ProviderRegistry()


def get_provider_registry() -> ProviderRegistry:
    return _default_registry
