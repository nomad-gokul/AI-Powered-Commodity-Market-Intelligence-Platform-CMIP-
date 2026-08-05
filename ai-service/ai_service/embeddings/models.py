"""Static embedding-model metadata: what embedding models exist per
provider and their output dimension.

Dimension is load-bearing, not informational: the `embeddings` table's
pgvector column (backend/app/modules/retrieval/models.py) is migrated to a
fixed width (1536, matching OpenAI's text-embedding-3-small - see
docs/ARCHITECTURE.md's Phase 5 section for the tradeoff). EmbeddingService
fails fast with a ConfigurationError, at construction time, if the
configured provider/model's registered dimension does not match that fixed
width - never lazily as a Postgres error on first write. Switching to a
different-dimension model is a deliberate future migration
(`ALTER COLUMN ... TYPE vector(N)` + re-embedding everything), not a
runtime toggle.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class EmbeddingModelInfo:
    provider: str
    model_id: str
    dimension: int
    max_input_tokens: int
    price_per_million_tokens: float | None
    """USD per 1,000,000 input tokens. None means unknown/not applicable
    (e.g. a self-hosted Ollama model has no per-token vendor cost)."""
    aliases: tuple[str, ...] = field(default_factory=tuple)


EMBEDDING_MODELS: tuple[EmbeddingModelInfo, ...] = (
    # --- OpenAI ---
    EmbeddingModelInfo(
        provider="openai",
        model_id="text-embedding-3-small",
        dimension=1536,
        max_input_tokens=8191,
        price_per_million_tokens=0.02,
    ),
    EmbeddingModelInfo(
        provider="openai",
        model_id="text-embedding-3-large",
        dimension=3072,
        max_input_tokens=8191,
        price_per_million_tokens=0.13,
    ),
    # --- Ollama (self-hosted; no vendor cost) ---
    EmbeddingModelInfo(
        provider="ollama",
        model_id="nomic-embed-text",
        dimension=768,
        max_input_tokens=8192,
        price_per_million_tokens=None,
    ),
)

DEFAULT_EMBEDDING_MODEL_BY_PROVIDER: dict[str, str] = {
    "openai": "text-embedding-3-small",
    "ollama": "nomic-embed-text",
}

EMBEDDING_DIMENSION = 1536
"""The `embeddings.embedding_vector` pgvector column's fixed width, chosen
to match the default provider's default model
(openai/text-embedding-3-small). See this module's docstring."""
