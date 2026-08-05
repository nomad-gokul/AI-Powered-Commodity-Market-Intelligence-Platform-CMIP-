"""Centralized application configuration, loaded from environment variables.

Only settings actually used by the current implementation live here.
Settings for later phases (object storage, LLM providers, OCR) are added
when their owning phase is implemented, not speculatively now.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LLMProviderName = Literal["groq", "claude", "openai", "ollama"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "CMIP"
    environment: str = "development"
    log_level: str = "INFO"
    api_v1_prefix: str = "/api/v1"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    # Database
    database_url: str = "postgresql+asyncpg://cmip:cmip_dev_password@localhost:5432/cmip"
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_echo: bool = False

    # Redis (rate limiting in Phase 1; job queue arrives in Phase 2)
    redis_url: str = "redis://localhost:6379/0"

    # Auth
    jwt_secret_key: str = "change-me-in-.env-to-a-random-64-char-string"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 30

    # Rate limiting
    login_rate_limit_attempts: int = 5
    login_rate_limit_window_seconds: int = 60

    # Document storage (Phase 2)
    storage_provider: str = "local"
    storage_local_root: str = "./data/documents"
    storage_s3_bucket: str = "cmip-documents"
    storage_s3_region: str = "us-east-1"
    storage_s3_endpoint_url: str | None = None
    storage_s3_access_key_id: str | None = None
    storage_s3_secret_access_key: str | None = None
    storage_signed_url_expire_seconds: int = 3600

    # Upload validation (Phase 2)
    upload_max_file_size_bytes: int = 50 * 1024 * 1024
    upload_allowed_extensions: list[str] = Field(
        default_factory=lambda: [".pdf", ".png", ".jpg", ".jpeg", ".tiff"]
    )
    upload_max_documents_per_user: int | None = None

    # Document processing (Phase 2)
    ocr_tesseract_cmd: str | None = None
    ocr_language: str = "eng"
    ocr_min_native_chars_per_page: int = 20
    chunk_size_tokens: int = 500
    chunk_overlap_tokens: int = 75
    processing_max_retries: int = 3
    processing_retry_backoff_base_seconds: int = 10

    # AI engine & LLM providers (Phase 3.1)
    # LLM_PROVIDER selects the default provider at runtime - business logic
    # never hardcodes a provider name. Literal[...] makes an invalid value
    # (e.g. a typo) fail fast at Settings() construction, not on first use.
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

    # Retrieval (Phase 5)
    # Unlike llm_provider/groq_model/... above, backend has no need for its
    # own embedding_provider/model fields: ai_service.embeddings.base.
    # EmbeddingProvider exposes `.model` directly (one provider instance is
    # bound to exactly one model, since dimension is fixed per instance),
    # so app.modules.retrieval.embedding_service reads that from the
    # provider object instead of duplicating the model name here. These
    # remaining fields ARE backend-only concerns - pure retrieval-
    # orchestration parameters ai-service has no reason to know about.
    embedding_dimension: int = 1536
    """Must match app.modules.retrieval.models.EMBEDDING_DIMENSION and
    ai_service.embeddings.models.EMBEDDING_DIMENSION - used defensively to
    fail fast if those three independently declared constants ever drift."""
    retrieval_top_k: int = 10
    retrieval_max_candidates: int = 200
    retrieval_graph_expansion_depth: int = 2

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    @model_validator(mode="after")
    def _validate_llm_config(self) -> "Settings":
        """Fail fast in production if the selected provider has no key.

        Deliberately lenient outside production: a developer switching
        LLM_PROVIDER locally without yet holding every provider's key is a
        normal, unblocked workflow. The equivalent "provider actually
        constructible" check for the selected provider still happens eagerly
        at factory-construction time (see ai_service.providers.factory) even in
        development - this validator only tightens things further for prod.
        """
        if not self.is_production:
            return self
        key_by_provider: dict[str, str | None] = {
            "groq": self.groq_api_key,
            "claude": self.claude_api_key,
            "openai": self.openai_api_key,
        }
        if self.llm_provider in key_by_provider and not key_by_provider[self.llm_provider]:
            raise ValueError(
                f"LLM_PROVIDER={self.llm_provider!r} requires "
                f"{self.llm_provider.upper()}_API_KEY to be set in production"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance (env is read once per process)."""
    return Settings()
