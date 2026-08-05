"""Provider-agnostic LLM request/response DTOs.

Moved out of ai-service.providers.base (Pre-Phase 5 AI Service Extraction):
these are pure data, consumed directly by business-module agents
(app.modules.extraction/.trust/.graph) as well as by every ai-service
provider implementation, so they live in `shared` rather than in either
side. The behavior that operates on them (LLMProvider, LLMClient,
StructuredOutputService) stays in ai-service.
"""

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


__all__ = [
    "LLMMessage",
    "LLMRequest",
    "LLMResponse",
    "LLMStreamChunk",
    "LLMToolCall",
    "LLMToolDefinition",
    "LLMUsage",
    "ProviderCapabilities",
    "ProviderHealth",
    "Role",
]
