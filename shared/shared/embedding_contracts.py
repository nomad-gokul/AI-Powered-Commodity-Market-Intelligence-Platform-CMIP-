"""Provider-agnostic embedding request/response DTOs.

Mirrors shared.ai_contracts' split for LLM calls (Pre-Phase 5): pure data
here, consumed directly by backend's EmbeddingService as well as every
ai-service EmbeddingProvider implementation. The behavior that operates on
them (the EmbeddingProvider ABC, its factory/registry) stays in ai-service.
Health reporting reuses shared.ai_contracts.ProviderHealth directly rather
than duplicating it - "is this provider reachable and authenticated" means
the same thing for an embedding provider as it does for an LLM provider.
"""

from dataclasses import dataclass

from pydantic import BaseModel, Field


class EmbeddingRequest(BaseModel):
    """A provider-agnostic batch embedding request. Batching a vendor's
    per-call text limit is the provider implementation's responsibility -
    callers pass as many texts as they have."""

    texts: list[str]
    model: str
    metadata: dict[str, str] = Field(default_factory=dict)


class EmbeddingUsage(BaseModel):
    prompt_tokens: int = 0
    total_tokens: int = 0


class EmbeddingResponse(BaseModel):
    vectors: list[list[float]]
    """One vector per input text, in the same order as EmbeddingRequest.texts."""
    provider: str
    model: str
    dimension: int
    usage: EmbeddingUsage
    latency_ms: float


@dataclass(frozen=True, slots=True)
class EmbeddingModelCapabilities:
    dimension: int
    max_input_tokens: int = 8191
    max_batch_size: int = 1


__all__ = [
    "EmbeddingModelCapabilities",
    "EmbeddingRequest",
    "EmbeddingResponse",
    "EmbeddingUsage",
]
