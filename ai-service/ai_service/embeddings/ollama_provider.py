"""OllamaEmbeddingProvider: real implementation against Ollama's local
`/api/embed` REST endpoint (batch-capable - takes a list of strings as
`input`). Implemented for real, NOT verified against a live Ollama
instance in this environment - see docs/ARCHITECTURE.md's provider testing
strategy (same caveat as ai_service.providers.ollama_provider.
OllamaProvider, which this mirrors, including talking to Ollama directly
over httpx rather than adding a dependency for a handful of JSON fields).
"""

import time
from typing import Any

import httpx
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


class OllamaEmbeddingProvider(EmbeddingProvider):
    def __init__(
        self, *, base_url: str, model: str, dimension: int, timeout_seconds: float = 60.0
    ) -> None:
        self._client = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout_seconds)
        self._model = model
        self._dimension = dimension

    @property
    def name(self) -> str:
        return "ollama"

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def model(self) -> str:
        return self._model

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        started = time.monotonic()
        model = request.model or self._model
        payload: dict[str, Any] = {"model": model, "input": request.texts}
        try:
            response = await self._client.post("/api/embed", json=payload)
            response.raise_for_status()
        except Exception as exc:
            raise self._translate_error(exc) from exc
        latency_ms = (time.monotonic() - started) * 1000

        body = response.json()
        vectors: list[list[float]] = body.get("embeddings", [])
        prompt_tokens = int(body.get("prompt_eval_count", 0))
        return EmbeddingResponse(
            vectors=vectors,
            provider=self.name,
            model=model,
            dimension=self._dimension,
            usage=EmbeddingUsage(prompt_tokens=prompt_tokens, total_tokens=prompt_tokens),
            latency_ms=latency_ms,
        )

    async def health_check(self) -> ProviderHealth:
        started = time.monotonic()
        try:
            response = await self._client.get("/api/tags")
            response.raise_for_status()
        except Exception as exc:  # noqa: BLE001 - health check reports failure, never raises
            return ProviderHealth(healthy=False, detail=f"{type(exc).__name__}: {exc}")
        return ProviderHealth(healthy=True, latency_ms=(time.monotonic() - started) * 1000)

    def _translate_error(self, exc: Exception) -> ProviderError:
        if isinstance(exc, httpx.TimeoutException):
            return ProviderTimeoutError(str(exc))
        if isinstance(exc, httpx.HTTPStatusError):
            status = exc.response.status_code
            if status == 429:
                return ProviderRateLimitError(str(exc))
            if status in (401, 403):
                return ProviderAuthError(str(exc))
            if status in (400, 404, 422):
                return ProviderInvalidRequestError(str(exc))
            return ProviderUnavailableError(str(exc))
        if isinstance(exc, httpx.HTTPError):
            return ProviderUnavailableError(str(exc))
        return ProviderError(f"{type(exc).__name__}: {exc}")
