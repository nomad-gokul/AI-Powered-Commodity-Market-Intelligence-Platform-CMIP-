"""LLMProvider: the single abstraction every LLM vendor integration
implements.

Everything above this layer (LLMClient, StructuredOutputService, and every
future agent) talks to `LLMProvider.generate()` and `ProviderCapabilities`
only - never to a vendor SDK type, never branching on `if provider.name ==
"groq"`. A capability the engine cares about (streaming, tool calling, JSON
schema output) is a boolean or int on ProviderCapabilities, checked once at
the call site that needs it; adding a fifth provider later means writing
one new class in this package, never touching a caller.
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field

Role = Literal["system", "user", "assistant", "tool"]


class LLMMessage(BaseModel):
    role: Role
    content: str
    tool_call_id: str | None = None
    name: str | None = None


class LLMToolDefinition(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class LLMToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any]


class LLMUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class LLMRequest(BaseModel):
    """A provider-agnostic generation request.

    Either supply `system_prompt`/`user_prompt` (the common single-turn
    case) or a full `messages` list (multi-turn, or when tool results need
    to be threaded back in) - `effective_messages()` reconciles the two so
    every provider implementation has exactly one place to read from.
    """

    system_prompt: str | None = None
    user_prompt: str | None = None
    messages: list[LLMMessage] = Field(default_factory=list)

    temperature: float = 0.0
    top_p: float = 1.0
    max_tokens: int | None = None
    tools: list[LLMToolDefinition] | None = None
    response_format: dict[str, Any] | None = None
    """A JSON schema the provider should constrain its output to, when
    ProviderCapabilities.supports_json_schema is True. Set by
    StructuredOutputService, not hand-authored by callers."""

    model: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    prompt_package_name: str | None = None
    prompt_package_version: str | None = None

    def effective_messages(self) -> list[LLMMessage]:
        if self.messages:
            return self.messages
        built: list[LLMMessage] = []
        if self.system_prompt:
            built.append(LLMMessage(role="system", content=self.system_prompt))
        if self.user_prompt:
            built.append(LLMMessage(role="user", content=self.user_prompt))
        return built


class LLMResponse(BaseModel):
    content: str | None
    tool_calls: list[LLMToolCall] = Field(default_factory=list)
    usage: LLMUsage
    provider: str
    model: str
    latency_ms: float
    finish_reason: str
    raw_response: Any = Field(default=None, exclude=True, repr=False)
    """The vendor SDK's raw response object, kept for debugging only -
    excluded from serialization/logging by construction (`exclude=True`),
    never persisted, never sent to structlog. See providers' own docstrings
    for why: it may contain the full completion text verbatim."""


class LLMStreamChunk(BaseModel):
    delta: str
    finish_reason: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    supports_streaming: bool = False
    supports_tools: bool = False
    supports_json_schema: bool = False
    supports_multimodal: bool = False
    supports_reasoning: bool = False
    supports_vision: bool = False
    supports_function_calling: bool = False
    max_context: int = 0
    max_output_tokens: int = 0


@dataclass(frozen=True, slots=True)
class ProviderHealth:
    healthy: bool
    detail: str = ""
    latency_ms: float | None = None
    checked_fields: dict[str, Any] = field(default_factory=dict)


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
        app.ai.exceptions.ProviderError taxonomy (ProviderRateLimitError,
        ProviderTimeoutError, ProviderUnavailableError, ProviderAuthError,
        ProviderInvalidRequestError) so LLMClient's retry policy can decide
        what's retryable without knowing which vendor raised it. This
        method does not itself retry - see LLMClient and the module
        docstring in app.ai.client.llm_client for why retries live in
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
