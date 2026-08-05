"""Observability primitives for LLM calls: one structured log line plus a
set of Prometheus metric updates per completed call, decoupled from
LLMClient so the client stays focused on request/retry/response plumbing.

Security note (see docs/ARCHITECTURE.md): record_llm_call logs metadata
only - provider, model, token counts, timing, correlation id - and NEVER
the prompt or completion text. LLMResponse.raw_response is a Pydantic
field with exclude=True for the same reason; nothing here ever touches it.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime

from shared.ai_contracts import LLMUsage
from shared.embedding_contracts import EmbeddingUsage

from ai_service.observability.logging import get_logger
from ai_service.observability.metrics import (
    embedding_call_duration_seconds,
    embedding_tokens_total,
    llm_call_duration_seconds,
    llm_call_failures_total,
    llm_estimated_cost_usd_total,
    llm_retries_total,
    llm_tokens_total,
)
from ai_service.providers.registry import get_provider_registry

logger = get_logger(__name__)


@dataclass(slots=True)
class LLMCallObservation:
    provider: str
    model: str
    latency_ms: float
    usage: LLMUsage
    success: bool
    retry_count: int = 0
    error_type: str | None = None
    request_id: str | None = None
    correlation_id: str | None = None
    prompt_package_name: str | None = None
    prompt_package_version: str | None = None
    estimated_cost_usd: float | None = None
    recorded_at: datetime = field(default_factory=lambda: datetime.now(UTC))


def estimate_cost(provider: str, model: str, usage: LLMUsage) -> float | None:
    return get_provider_registry().estimate_cost_usd(provider, model, usage)


def record_llm_call(observation: LLMCallObservation) -> None:
    llm_call_duration_seconds.labels(
        provider=observation.provider, model=observation.model
    ).observe(observation.latency_ms / 1000)
    if observation.success:
        llm_tokens_total.labels(
            provider=observation.provider, model=observation.model, kind="prompt"
        ).inc(observation.usage.prompt_tokens)
        llm_tokens_total.labels(
            provider=observation.provider, model=observation.model, kind="completion"
        ).inc(observation.usage.completion_tokens)
        if observation.estimated_cost_usd is not None:
            llm_estimated_cost_usd_total.labels(
                provider=observation.provider, model=observation.model
            ).inc(observation.estimated_cost_usd)
    else:
        llm_call_failures_total.labels(
            provider=observation.provider,
            model=observation.model,
            error_type=observation.error_type or "unknown",
        ).inc()
    if observation.retry_count:
        llm_retries_total.labels(provider=observation.provider, model=observation.model).inc(
            observation.retry_count
        )

    logger.info(
        "llm_call",
        provider=observation.provider,
        model=observation.model,
        latency_ms=round(observation.latency_ms, 2),
        prompt_tokens=observation.usage.prompt_tokens,
        completion_tokens=observation.usage.completion_tokens,
        total_tokens=observation.usage.total_tokens,
        success=observation.success,
        retry_count=observation.retry_count,
        error_type=observation.error_type,
        request_id=observation.request_id,
        correlation_id=observation.correlation_id,
        prompt_package_name=observation.prompt_package_name,
        prompt_package_version=observation.prompt_package_version,
        estimated_cost_usd=observation.estimated_cost_usd,
    )


def record_embedding_call(
    *, provider: str, model: str, latency_ms: float, usage: EmbeddingUsage, item_count: int
) -> None:
    """The embedding-call counterpart to record_llm_call() - deliberately
    simpler (no cost estimation, no retry/failure taxonomy): embeddings
    have no per-provider retry policy of their own (EmbeddingService calls
    the provider directly, no EmbeddingClient wrapper) and no reference
    pricing table exists yet (Phase 5 scope - see docs/ARCHITECTURE.md).
    """
    embedding_call_duration_seconds.labels(provider=provider, model=model).observe(
        latency_ms / 1000
    )
    embedding_tokens_total.labels(provider=provider, model=model).inc(usage.total_tokens)
    logger.info(
        "embedding_call",
        provider=provider,
        model=model,
        latency_ms=round(latency_ms, 2),
        total_tokens=usage.total_tokens,
        item_count=item_count,
    )
