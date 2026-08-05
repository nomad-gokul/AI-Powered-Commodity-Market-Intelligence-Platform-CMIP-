"""GroqProvider: the development-default LLMProvider.

Uses the official `groq` SDK. This is the one provider with a real,
credential-backed integration test in this environment (see
tests/integration/test_groq_live.py) - Claude/OpenAI/Ollama below are
implemented for real against their official SDKs but unverified here, the
same precedent PaddleOCR set in Phase 2 (see docs/ARCHITECTURE.md).
"""

import time
from typing import Any

from groq import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    AsyncGroq,
    AuthenticationError,
    BadRequestError,
    RateLimitError,
    UnprocessableEntityError,
)
from shared.ai_contracts import ProviderCapabilities, ProviderHealth

from ai_service.providers._chat_completions_base import (
    ChatCompletionsCompatibleProvider,
    SDKErrorMap,
)
from ai_service.providers.models import GROQ_CAPABILITIES

_ERRORS = SDKErrorMap(
    rate_limit=RateLimitError,
    authentication=AuthenticationError,
    bad_request=BadRequestError,
    unprocessable_entity=UnprocessableEntityError,
    timeout=APITimeoutError,
    connection=APIConnectionError,
    api_error=APIError,
)


class GroqProvider(ChatCompletionsCompatibleProvider):
    def __init__(self, *, api_key: str, timeout_seconds: float = 60.0) -> None:
        super().__init__(errors=_ERRORS)
        # max_retries=0: retry policy lives in LLMClient only (see that
        # module's docstring) - the SDK's own default retry loop would
        # otherwise compound with LLMClient's, multiplying worst-case
        # latency for identical failures.
        self._client = AsyncGroq(api_key=api_key, timeout=timeout_seconds, max_retries=0)

    @property
    def name(self) -> str:
        return "groq"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return GROQ_CAPABILITIES

    @property
    def _completions(self) -> Any:
        return self._client.chat.completions

    async def health_check(self) -> ProviderHealth:
        started = time.monotonic()
        try:
            await self._client.models.list()
        except Exception as exc:  # noqa: BLE001 - health check reports failure, never raises
            return ProviderHealth(healthy=False, detail=f"{type(exc).__name__}: {exc}")
        return ProviderHealth(healthy=True, latency_ms=(time.monotonic() - started) * 1000)
