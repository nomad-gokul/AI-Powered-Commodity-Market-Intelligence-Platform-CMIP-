"""LLMClient: the only thing above the provider layer ever talks to.

This is the codebase's "AIClient" in the sense used across
docs/ARCHITECTURE.md's Pre-Phase 5 section: send a request, receive a
response, report health, select a provider, and record observability -
kept under its existing, working name (LLMClient) rather than renamed,
since a rename here is a purely cosmetic diff across every call site for
zero functional benefit.

Retry policy lives here, and ONLY here: providers translate vendor SDK
exceptions into shared.ai_exceptions.ProviderError and never retry
themselves (each provider constructs its vendor client with
max_retries=0) - retrying at both the SDK layer and here would compound
latency for every identical failure. Only errors in
RETRYABLE_PROVIDER_ERRORS (rate limit, timeout, unavailable) are retried;
auth and invalid-request errors fail immediately since retrying them can
never succeed.

Security: this class logs call METADATA only (provider, model, token
counts, latency, correlation id) via ai_service.observability.tracking -
prompt and completion text are never logged. The one place vendor *error*
text is logged (a retry warning) is passed through redact_secrets first,
in case an SDK error string happens to echo back part of the request.
"""

import asyncio
import uuid
from dataclasses import dataclass
from functools import lru_cache

from shared.ai_contracts import LLMRequest, LLMResponse, LLMUsage, ProviderHealth
from shared.ai_exceptions import RETRYABLE_PROVIDER_ERRORS, ProviderError

from ai_service.config.settings import get_ai_settings
from ai_service.observability.logging import get_logger
from ai_service.observability.redaction import redact_secrets
from ai_service.observability.tracking import LLMCallObservation, estimate_cost, record_llm_call
from ai_service.providers.base import LLMProvider
from ai_service.providers.factory import get_llm_provider

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class LLMClientRetryPolicy:
    max_attempts: int = 3
    backoff_base_seconds: float = 1.0
    backoff_multiplier: float = 2.0

    def delay_for_attempt(self, attempt: int) -> float:
        """attempt is 1-indexed: the delay BEFORE the given retry attempt."""
        return self.backoff_base_seconds * (self.backoff_multiplier ** (attempt - 1))


class LLMClient:
    def __init__(
        self, provider: LLMProvider, *, retry_policy: LLMClientRetryPolicy | None = None
    ) -> None:
        self._provider = provider
        self._retry_policy = retry_policy or LLMClientRetryPolicy()

    @property
    def provider(self) -> LLMProvider:
        return self._provider

    async def generate(
        self, request: LLMRequest, *, correlation_id: str | None = None
    ) -> LLMResponse:
        request_id = str(uuid.uuid4())
        correlation_id = correlation_id or request_id
        attempt = 0
        retries_used = 0

        while True:
            attempt += 1
            try:
                response = await self._provider.generate(request)
            except ProviderError as exc:
                retryable = isinstance(exc, RETRYABLE_PROVIDER_ERRORS)
                if retryable and attempt < self._retry_policy.max_attempts:
                    retries_used += 1
                    logger.warning(
                        "llm_call_retrying",
                        provider=self._provider.name,
                        model=request.model,
                        attempt=attempt,
                        error_type=type(exc).__name__,
                        error=redact_secrets(exc.message),
                        request_id=request_id,
                        correlation_id=correlation_id,
                    )
                    await asyncio.sleep(self._retry_policy.delay_for_attempt(attempt))
                    continue

                record_llm_call(
                    LLMCallObservation(
                        provider=self._provider.name,
                        model=request.model,
                        latency_ms=0.0,
                        usage=LLMUsage(),
                        success=False,
                        retry_count=retries_used,
                        error_type=type(exc).__name__,
                        request_id=request_id,
                        correlation_id=correlation_id,
                        prompt_package_name=request.prompt_package_name,
                        prompt_package_version=request.prompt_package_version,
                    )
                )
                raise

            record_llm_call(
                LLMCallObservation(
                    provider=self._provider.name,
                    model=request.model,
                    latency_ms=response.latency_ms,
                    usage=response.usage,
                    success=True,
                    retry_count=retries_used,
                    request_id=request_id,
                    correlation_id=correlation_id,
                    prompt_package_name=request.prompt_package_name,
                    prompt_package_version=request.prompt_package_version,
                    estimated_cost_usd=estimate_cost(
                        self._provider.name, request.model, response.usage
                    ),
                )
            )
            return response

    async def health_check(self) -> ProviderHealth:
        """Passthrough to the underlying provider's health check.

        Added in Pre-Phase 5 (AI Service Extraction): ProviderHealth and
        LLMProvider.health_check() already existed per-provider, but
        nothing surfaced health at the client level - the layer everything
        above actually depends on. Purely additive; no existing behavior
        changes.
        """
        return await self._provider.health_check()


@lru_cache
def get_llm_client() -> LLMClient:
    """The process-wide default LLMClient, wrapping get_llm_provider()'s
    default provider with retry policy from AISettings."""
    settings = get_ai_settings()
    return LLMClient(
        get_llm_provider(),
        retry_policy=LLMClientRetryPolicy(
            max_attempts=settings.llm_max_retries,
            backoff_base_seconds=settings.llm_retry_backoff_base_seconds,
        ),
    )
