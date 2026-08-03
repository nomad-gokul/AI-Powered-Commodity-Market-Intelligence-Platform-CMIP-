"""OllamaProvider: real implementation against Ollama's local REST API
(http://<host>/api/chat). Implemented for real, NOT verified against a
live Ollama instance in this environment - see docs/ARCHITECTURE.md's
provider testing strategy.

Ollama has no first-party async Python SDK in the same sense Groq/OpenAI/
Anthropic ship one, and it's a local HTTP server rather than a hosted API -
so this talks to it directly over httpx rather than adding a dependency on
the (thin, community-maintained) `ollama` package for what is a handful of
JSON fields.
"""

import time
from typing import Any

import httpx

from app.ai.exceptions import (
    ProviderAuthError,
    ProviderError,
    ProviderInvalidRequestError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from app.ai.providers.base import (
    LLMProvider,
    LLMRequest,
    LLMResponse,
    LLMToolCall,
    LLMUsage,
    ProviderCapabilities,
    ProviderHealth,
)
from app.ai.providers.models import OLLAMA_CAPABILITIES


class OllamaProvider(LLMProvider):
    def __init__(self, *, base_url: str, timeout_seconds: float = 60.0) -> None:
        self._client = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout_seconds)

    @property
    def name(self) -> str:
        return "ollama"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return OLLAMA_CAPABILITIES

    def _build_payload(self, request: LLMRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": [
                {"role": m.role, "content": m.content} for m in request.effective_messages()
            ],
            "stream": False,
            "options": {"temperature": request.temperature, "top_p": request.top_p},
        }
        if request.max_tokens is not None:
            payload["options"]["num_predict"] = request.max_tokens
        if request.response_format is not None:
            payload["format"] = request.response_format
        if request.tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
                for t in request.tools
            ]
        return payload

    async def generate(self, request: LLMRequest) -> LLMResponse:
        started = time.monotonic()
        try:
            response = await self._client.post("/api/chat", json=self._build_payload(request))
            response.raise_for_status()
        except Exception as exc:
            raise self._translate_error(exc) from exc
        latency_ms = (time.monotonic() - started) * 1000

        body = response.json()
        message = body.get("message", {})
        raw_tool_calls = message.get("tool_calls") or []
        tool_calls = [
            LLMToolCall(
                id=str(index),
                name=call["function"]["name"],
                arguments=call["function"].get("arguments", {}),
            )
            for index, call in enumerate(raw_tool_calls)
        ]
        return LLMResponse(
            content=message.get("content"),
            tool_calls=tool_calls,
            usage=LLMUsage(
                prompt_tokens=body.get("prompt_eval_count", 0),
                completion_tokens=body.get("eval_count", 0),
                total_tokens=body.get("prompt_eval_count", 0) + body.get("eval_count", 0),
            ),
            provider=self.name,
            model=request.model,
            latency_ms=latency_ms,
            finish_reason=body.get("done_reason") or ("stop" if body.get("done") else "unknown"),
            raw_response=body,
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
