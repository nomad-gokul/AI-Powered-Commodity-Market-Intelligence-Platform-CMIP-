"""ProviderFactory: constructs the configured LLMProvider from AISettings.

This is the ONLY place in the codebase allowed to know all four concrete
provider classes exist - everything above it (LLMClient, agents, future
services) receives an `LLMProvider` and never imports GroqProvider,
ClaudeProvider, etc. directly. Adding a fifth provider means adding one
branch here; no other file changes.

Fails fast: a missing API key or an unknown model raises
ConfigurationError immediately, at construction time - not three requests
into a pipeline run as an opaque vendor 401/400.
"""

from functools import lru_cache

from shared.ai_exceptions import ConfigurationError

from ai_service.config.settings import AISettings, get_ai_settings
from ai_service.providers.base import LLMProvider
from ai_service.providers.claude_provider import ClaudeProvider
from ai_service.providers.groq_provider import GroqProvider
from ai_service.providers.ollama_provider import OllamaProvider
from ai_service.providers.openai_provider import OpenAIProvider
from ai_service.providers.registry import get_provider_registry


def build_provider(settings: AISettings, *, provider_name: str | None = None) -> LLMProvider:
    name = provider_name or settings.llm_provider
    registry = get_provider_registry()
    timeout = settings.llm_request_timeout_seconds

    if name == "groq":
        if not settings.groq_api_key:
            raise ConfigurationError("GROQ_API_KEY is required when LLM_PROVIDER=groq")
        registry.get_model_info("groq", settings.groq_model)
        return GroqProvider(api_key=settings.groq_api_key, timeout_seconds=timeout)

    if name == "claude":
        if not settings.claude_api_key:
            raise ConfigurationError("CLAUDE_API_KEY is required when LLM_PROVIDER=claude")
        registry.get_model_info("claude", settings.claude_model)
        return ClaudeProvider(api_key=settings.claude_api_key, timeout_seconds=timeout)

    if name == "openai":
        if not settings.openai_api_key:
            raise ConfigurationError("OPENAI_API_KEY is required when LLM_PROVIDER=openai")
        registry.get_model_info("openai", settings.openai_model)
        return OpenAIProvider(api_key=settings.openai_api_key, timeout_seconds=timeout)

    if name == "ollama":
        registry.get_model_info("ollama", settings.ollama_model)
        return OllamaProvider(base_url=settings.ollama_base_url, timeout_seconds=timeout)

    raise ConfigurationError(
        f"Unknown LLM provider {name!r}. Supported: groq, claude, openai, ollama"
    )


@lru_cache
def get_llm_provider() -> LLMProvider:
    """The process-wide default provider, built from AISettings.llm_provider.

    Cached like get_ai_settings(): constructed once per process, so
    misconfiguration surfaces the first time anything actually needs a
    provider, not lazily inside a request handler after other work has
    already happened.
    """
    return build_provider(get_ai_settings())
