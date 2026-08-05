"""LLMProvider: the single abstraction every LLM vendor integration
implements.

Everything above this layer (LLMClient, StructuredOutputService, and every
future agent) talks to `LLMProvider.generate()` and `ProviderCapabilities`
only - never to a vendor SDK type, never branching on `if provider.name ==
"groq"`. A capability the engine cares about (streaming, tool calling, JSON
schema output) is a boolean or int on ProviderCapabilities, checked once at
the call site that needs it; adding a fifth provider later means writing
one new class in this package, never touching a caller.

The request/response DTOs (LLMMessage, LLMRequest, LLMResponse, ...) live
in shared.ai_contracts, not here (Pre-Phase 5 AI Service Extraction) -
business-module agents construct/consume them directly as data, so they
are a shared contract; this ABC is the one piece of real behavior above
them.
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from shared.ai_contracts import (
    LLMRequest,
    LLMResponse,
    LLMStreamChunk,
    ProviderCapabilities,
    ProviderHealth,
)


class LLMProvider(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def capabilities(self) -> ProviderCapabilities: ...

    @abstractmethod
    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Perform one generation call and return a normalized LLMResponse.

        Implementations translate vendor SDK exceptions into the
        shared.ai_exceptions.ProviderError taxonomy (ProviderRateLimitError,
        ProviderTimeoutError, ProviderUnavailableError, ProviderAuthError,
        ProviderInvalidRequestError) so LLMClient's retry policy can decide
        what's retryable without knowing which vendor raised it. This
        method does not itself retry - see LLMClient and the module
        docstring in ai_service.client.llm_client for why retries live in
        exactly one place.
        """
        ...

    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMStreamChunk]:
        """Stream a generation response. Only implemented by providers
        whose capabilities.supports_streaming is True; the default raises
        so calling it on an incapable provider fails immediately and
        clearly rather than silently falling back to non-streaming."""
        raise NotImplementedError(f"{self.name} does not support streaming")
        yield  # pragma: no cover - makes this an async generator for mypy

    @abstractmethod
    async def health_check(self) -> ProviderHealth:
        """A cheap, low-latency call proving the provider is reachable and
        credentials are valid. Never a full generation call."""
        ...
