"""OpenAIEmbeddingProvider: real implementation against the official
`openai` SDK's embeddings endpoint. Implemented for real, NOT verified
against a live API key in this environment - see docs/ARCHITECTURE.md's
provider testing strategy (same caveat as
ai_service.providers.openai_provider.OpenAIProvider, which this mirrors).

No new dependency: the `openai` package is already installed for
ai_service.providers.openai_provider.OpenAIProvider and exposes
`.embeddings.create()` on the same AsyncOpenAI client.
"""

import time

from openai import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    BadRequestError,
    RateLimitError,
)
from shared.ai_contracts import ProviderHealth
from shared.ai_exceptions import (
    ProviderAuthError,
    ProviderError,
    ProviderInvalidRequestError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from shared.embedding_contracts import EmbeddingRequest, EmbeddingResponse, EmbeddingUsage

from ai_service.embeddings.base import EmbeddingProvider


class OpenAIEmbeddingProvider(EmbeddingProvider):
    def __init__(
        self, *, api_key: str, model: str, dimension: int, timeout_seconds: float = 60.0
    ) -> None:
        # max_retries=0: retry policy belongs to the caller (backend's
        # EmbeddingService), same rationale as OpenAIProvider's LLM client.
        self._client = AsyncOpenAI(api_key=api_key, timeout=timeout_seconds, max_retries=0)
        self._model = model
        self._dimension = dimension

    @property
    def name(self) -> str:
        return "openai"

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def model(self) -> str:
        return self._model

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        started = time.monotonic()
        model = request.model or self._model
        try:
            response = await self._client.embeddings.create(model=model, input=request.texts)
        except Exception as exc:
            raise self._translate_error(exc) from exc
        latency_ms = (time.monotonic() - started) * 1000

        ordered = sorted(response.data, key=lambda item: item.index)
        usage = response.usage
        return EmbeddingResponse(
            vectors=[list(item.embedding) for item in ordered],
            provider=self.name,
            model=response.model,
            dimension=self._dimension,
            usage=EmbeddingUsage(
                prompt_tokens=usage.prompt_tokens if usage else 0,
                total_tokens=usage.total_tokens if usage else 0,
            ),
            latency_ms=latency_ms,
        )

    async def health_check(self) -> ProviderHealth:
        started = time.monotonic()
        try:
            async for _ in self._client.models.list():
                break
        except Exception as exc:  # noqa: BLE001 - health check reports failure, never raises
            return ProviderHealth(healthy=False, detail=f"{type(exc).__name__}: {exc}")
        return ProviderHealth(healthy=True, latency_ms=(time.monotonic() - started) * 1000)

    def _translate_error(self, exc: Exception) -> ProviderError:
        if isinstance(exc, RateLimitError):
            return ProviderRateLimitError(str(exc))
        if isinstance(exc, APITimeoutError):
            return ProviderTimeoutError(str(exc))
        if isinstance(exc, APIConnectionError):
            return ProviderUnavailableError(str(exc))
        if isinstance(exc, AuthenticationError):
            return ProviderAuthError(str(exc))
        if isinstance(exc, BadRequestError):
            return ProviderInvalidRequestError(str(exc))
        if isinstance(exc, APIError):
            return ProviderUnavailableError(str(exc))
        return ProviderError(f"{type(exc).__name__}: {exc}")
