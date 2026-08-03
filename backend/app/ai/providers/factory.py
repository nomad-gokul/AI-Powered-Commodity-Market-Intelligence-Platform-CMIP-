"""ProviderFactory: constructs the configured LLMProvider from Settings.

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

from app.ai.exceptions import ConfigurationError
from app.ai.providers.base import LLMProvider
from app.ai.providers.claude_provider import ClaudeProvider
from app.ai.providers.groq_provider import GroqProvider
from app.ai.providers.ollama_provider import OllamaProvider
from app.ai.providers.openai_provider import OpenAIProvider
from app.ai.providers.registry import get_provider_registry
from app.core.config import Settings, get_settings


def build_provider(settings: Settings, *, provider_name: str | None = None) -> LLMProvider:
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
    """The process-wide default provider, built from Settings.llm_provider.

    Cached like get_settings()/get_storage_provider(): constructed once per
    process, so misconfiguration surfaces the first time anything actually
    needs a provider, not lazily inside a request handler after other work
    has already happened.
    """
    return build_provider(get_settings())
