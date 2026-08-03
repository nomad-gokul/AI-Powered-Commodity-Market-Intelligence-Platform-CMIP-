"""OpenAIProvider: real implementation against the official `openai` SDK.
Implemented for real, NOT verified with a live API key in this environment
- see docs/ARCHITECTURE.md's provider testing strategy.

OpenAI's chat.completions API is the shape Groq's SDK was itself modeled
on, so this reuses ChatCompletionsCompatibleProvider entirely - only the
client construction, capabilities, and exception classes differ.
"""

import time
from typing import Any

from openai import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    BadRequestError,
    RateLimitError,
    UnprocessableEntityError,
)

from app.ai.providers._chat_completions_base import ChatCompletionsCompatibleProvider, SDKErrorMap
from app.ai.providers.base import ProviderCapabilities, ProviderHealth
from app.ai.providers.models import OPENAI_CAPABILITIES

_ERRORS = SDKErrorMap(
    rate_limit=RateLimitError,
    authentication=AuthenticationError,
    bad_request=BadRequestError,
    unprocessable_entity=UnprocessableEntityError,
    timeout=APITimeoutError,
    connection=APIConnectionError,
    api_error=APIError,
)


class OpenAIProvider(ChatCompletionsCompatibleProvider):
    def __init__(self, *, api_key: str, timeout_seconds: float = 60.0) -> None:
        super().__init__(errors=_ERRORS)
        # max_retries=0: retry policy lives in LLMClient only - see
        # groq_provider.py's identical comment for why.
        self._client = AsyncOpenAI(api_key=api_key, timeout=timeout_seconds, max_retries=0)

    @property
    def name(self) -> str:
        return "openai"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return OPENAI_CAPABILITIES

    @property
    def _completions(self) -> Any:
        return self._client.chat.completions

    async def health_check(self) -> ProviderHealth:
        started = time.monotonic()
        try:
            async for _ in self._client.models.list():
                break
        except Exception as exc:  # noqa: BLE001 - health check reports failure, never raises
            return ProviderHealth(healthy=False, detail=f"{type(exc).__name__}: {exc}")
        return ProviderHealth(healthy=True, latency_ms=(time.monotonic() - started) * 1000)
