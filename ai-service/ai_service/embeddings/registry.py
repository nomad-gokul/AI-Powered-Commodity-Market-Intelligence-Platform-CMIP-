"""EmbeddingModelRegistry: the single source of truth for "what embedding
models exist" and their dimension - mirrors
ai_service.providers.registry.ProviderRegistry exactly.

A typo'd model name (OPENAI_EMBEDDING_MODEL=text-embeding-3-small) fails
fast here, at provider-construction time, with a clear ConfigurationError -
not on the first retrieval request as an opaque vendor 400.
"""

from shared.ai_exceptions import ConfigurationError

from ai_service.embeddings.models import (
    DEFAULT_EMBEDDING_MODEL_BY_PROVIDER,
    EMBEDDING_MODELS,
    EmbeddingModelInfo,
)


class EmbeddingModelRegistry:
    def __init__(self, models: tuple[EmbeddingModelInfo, ...] = EMBEDDING_MODELS) -> None:
        self._by_key: dict[tuple[str, str], EmbeddingModelInfo] = {}
        for info in models:
            self._by_key[(info.provider, info.model_id)] = info
            for alias in info.aliases:
                self._by_key[(info.provider, alias)] = info

    def get_model_info(self, provider: str, model_id: str) -> EmbeddingModelInfo:
        try:
            return self._by_key[(provider, model_id)]
        except KeyError:
            known = sorted({key[1] for key in self._by_key if key[0] == provider})
            raise ConfigurationError(
                f"Unknown embedding model {model_id!r} for provider {provider!r}. "
                f"Known models: {known or '(none registered)'}",
                details={"provider": provider, "model": model_id, "known_models": known},
            ) from None

    def default_model(self, provider: str) -> str:
        try:
            return DEFAULT_EMBEDDING_MODEL_BY_PROVIDER[provider]
        except KeyError:
            raise ConfigurationError(
                f"No default embedding model configured for provider {provider!r}"
            ) from None

    def list_models(self, provider: str) -> list[EmbeddingModelInfo]:
        seen: set[str] = set()
        result: list[EmbeddingModelInfo] = []
        for (prov, _key), info in self._by_key.items():
            if prov == provider and info.model_id not in seen:
                seen.add(info.model_id)
                result.append(info)
        return result


_default_registry = EmbeddingModelRegistry()


def get_embedding_model_registry() -> EmbeddingModelRegistry:
    return _default_registry
