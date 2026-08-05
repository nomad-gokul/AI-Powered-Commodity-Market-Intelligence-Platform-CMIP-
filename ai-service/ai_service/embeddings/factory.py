"""EmbeddingProviderFactory: constructs the configured EmbeddingProvider
from AISettings - mirrors ai_service.providers.factory.build_provider
exactly, including its fail-fast philosophy.

This is the ONLY place in the codebase allowed to know both concrete
embedding provider classes exist - everything above it (backend's
EmbeddingService) receives an `EmbeddingProvider` and never imports
OpenAIEmbeddingProvider/OllamaEmbeddingProvider directly.
"""

from functools import lru_cache

from shared.ai_exceptions import ConfigurationError

from ai_service.config.settings import AISettings, get_ai_settings
from ai_service.embeddings.base import EmbeddingProvider
from ai_service.embeddings.ollama_provider import OllamaEmbeddingProvider
from ai_service.embeddings.openai_provider import OpenAIEmbeddingProvider
from ai_service.embeddings.registry import get_embedding_model_registry


def build_embedding_provider(
    settings: AISettings, *, provider_name: str | None = None
) -> EmbeddingProvider:
    name = provider_name or settings.embedding_provider
    registry = get_embedding_model_registry()
    timeout = settings.llm_request_timeout_seconds

    if name == "openai":
        if not settings.openai_api_key:
            raise ConfigurationError("OPENAI_API_KEY is required when EMBEDDING_PROVIDER=openai")
        info = registry.get_model_info("openai", settings.openai_embedding_model)
        return OpenAIEmbeddingProvider(
            api_key=settings.openai_api_key,
            model=info.model_id,
            dimension=info.dimension,
            timeout_seconds=timeout,
        )

    if name == "ollama":
        info = registry.get_model_info("ollama", settings.ollama_embedding_model)
        return OllamaEmbeddingProvider(
            base_url=settings.ollama_base_url,
            model=info.model_id,
            dimension=info.dimension,
            timeout_seconds=timeout,
        )

    raise ConfigurationError(f"Unknown embedding provider {name!r}. Supported: openai, ollama")


@lru_cache
def get_embedding_provider() -> EmbeddingProvider:
    """The process-wide default embedding provider, built from
    AISettings.embedding_provider. Cached like get_llm_provider(): built
    once per process, so misconfiguration surfaces the first time anything
    actually needs an embedding, not lazily inside a request handler."""
    return build_embedding_provider(get_ai_settings())
