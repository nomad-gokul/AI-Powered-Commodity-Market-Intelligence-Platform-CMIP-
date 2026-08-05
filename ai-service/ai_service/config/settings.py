"""AISettings: ai-service's own configuration, read independently from the
same environment variables backend's app.core.config.Settings also reads.

New in Pre-Phase 5 (AI Service Extraction). Two pydantic-settings classes
parsing the same `.env` is the deliberate, zero-coupling seam for this
monorepo boundary - not duplication to clean up later, but the actual
point of the exercise: ai-service must never import app.core (that would
recreate the exact reverse-coupling this refactor removes, and would block
ai-service from ever being deployed independently). Backend keeps its own
llm_*/groq_*/claude_*/openai_*/ollama_* fields because app.modules.
extraction.api reads them directly for a model-name lookup, independent of
anything in ai-service.

Field names and defaults are identical to backend's Settings by design -
see docs/ARCHITECTURE.md's Pre-Phase 5 section for the full rationale.
"""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

LLMProviderName = Literal["groq", "claude", "openai", "ollama"]
EmbeddingProviderName = Literal["openai", "ollama"]


class AISettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"

    llm_provider: LLMProviderName = "groq"
    llm_request_timeout_seconds: float = 60.0
    llm_max_retries: int = 3
    llm_retry_backoff_base_seconds: float = 1.0

    groq_api_key: str | None = None
    groq_model: str = "llama-3.3-70b-versatile"

    claude_api_key: str | None = None
    claude_model: str = "claude-sonnet-5"

    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1"

    # --- Embeddings & retrieval (Phase 5) ---
    # Field names/defaults mirror backend's Settings by the same design as
    # the llm_*/groq_*/... fields above - see this module's docstring.
    embedding_provider: EmbeddingProviderName = "openai"
    openai_embedding_model: str = "text-embedding-3-small"
    ollama_embedding_model: str = "nomic-embed-text"

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"


@lru_cache
def get_ai_settings() -> AISettings:
    """Return a cached AISettings instance (env is read once per process)."""
    return AISettings()
