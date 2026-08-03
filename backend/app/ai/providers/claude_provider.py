"""ClaudeProvider: real implementation against the official `anthropic`
SDK. Implemented for real, NOT verified with a live API key in this
environment - see docs/ARCHITECTURE.md's provider testing strategy.

Anthropic's Messages API differs from the OpenAI-shaped chat.completions
APIs (Groq/OpenAI here) in three ways this class has to bridge:

1. `system` is a dedicated top-level parameter, not a message with
   role="system" - LLMRequest's effective_messages() still models it as a
   message, so this provider pulls it back out.
2. There is no native JSON-schema response format. Structured output is
   achieved by forcing a single synthetic tool call (see
   _structured_output_tool) and reading the tool's `input` back out - the
   result is written into LLMResponse.content as JSON text so
   StructuredOutputService can treat every provider identically and never
   needs to know which mechanism produced the JSON.
3. Tool results come back as content *blocks* within a message, not a
   separate `tool_calls` field on the SDK response - handled in
   _parse_content_blocks.
"""

import json
import time
from typing import Any

from anthropic import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    AsyncAnthropic,
    AuthenticationError,
    BadRequestError,
    RateLimitError,
    UnprocessableEntityError,
)
from anthropic import omit as anthropic_omit

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
from app.ai.providers.models import CLAUDE_CAPABILITIES

_STRUCTURED_OUTPUT_TOOL_NAME = "emit_structured_response"
_DEFAULT_MAX_TOKENS = 4096


class ClaudeProvider(LLMProvider):
    def __init__(self, *, api_key: str, timeout_seconds: float = 60.0) -> None:
        # max_retries=0: retry policy lives in LLMClient only - see
        # groq_provider.py's identical comment for why.
        self._client = AsyncAnthropic(api_key=api_key, timeout=timeout_seconds, max_retries=0)

    @property
    def name(self) -> str:
        return "claude"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return CLAUDE_CAPABILITIES

    def _split_system_and_messages(
        self, request: LLMRequest
    ) -> tuple[str | None, list[dict[str, Any]]]:
        system_parts: list[str] = []
        messages: list[dict[str, Any]] = []
        for message in request.effective_messages():
            if message.role == "system":
                system_parts.append(message.content)
            elif message.role == "tool":
                messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": message.tool_call_id or "",
                                "content": message.content,
                            }
                        ],
                    }
                )
            else:
                messages.append({"role": message.role, "content": message.content})
        return ("\n".join(system_parts) or None, messages)

    def _build_tools(self, request: LLMRequest) -> tuple[list[dict[str, Any]], Any]:
        """Returns (tools, tool_choice). tool_choice's real type is a union
        of several Anthropic TypedDicts plus their Omit sentinel; typed
        `Any` here deliberately since this method builds a plain dict,
        not one of those TypedDicts, and mypy can't structurally match a
        dict[str, Any] against a TypedDict union - the actual shape is
        verified by the Anthropic API itself, not by mypy, for this one
        call site.
        """
        if request.response_format is not None:
            tool = {
                "name": _STRUCTURED_OUTPUT_TOOL_NAME,
                "description": "Emit the structured response matching the required schema.",
                "input_schema": request.response_format,
            }
            return [tool], {"type": "tool", "name": _STRUCTURED_OUTPUT_TOOL_NAME}
        if request.tools:
            tools = [
                {"name": t.name, "description": t.description, "input_schema": t.parameters}
                for t in request.tools
            ]
            return tools, anthropic_omit
        return [], anthropic_omit

    async def generate(self, request: LLMRequest) -> LLMResponse:
        system, messages = self._split_system_and_messages(request)
        tools, tool_choice = self._build_tools(request)

        started = time.monotonic()
        try:
            message = await self._client.messages.create(
                model=request.model,
                max_tokens=request.max_tokens or _DEFAULT_MAX_TOKENS,
                messages=messages,  # type: ignore[arg-type]
                system=system if system is not None else anthropic_omit,
                temperature=request.temperature,
                top_p=request.top_p,
                tools=tools or anthropic_omit,  # type: ignore[arg-type]
                tool_choice=tool_choice,
            )
        except Exception as exc:
            raise self._translate_error(exc) from exc
        latency_ms = (time.monotonic() - started) * 1000

        content, tool_calls = self._parse_content_blocks(
            message.content, request.response_format is not None
        )
        usage = message.usage
        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            usage=LLMUsage(
                prompt_tokens=usage.input_tokens,
                completion_tokens=usage.output_tokens,
                total_tokens=usage.input_tokens + usage.output_tokens,
            ),
            provider=self.name,
            model=request.model,
            latency_ms=latency_ms,
            finish_reason=message.stop_reason or "unknown",
            raw_response=message,
        )

    def _parse_content_blocks(
        self, blocks: list[Any], is_structured_output: bool
    ) -> tuple[str | None, list[LLMToolCall]]:
        text_parts: list[str] = []
        tool_calls: list[LLMToolCall] = []
        structured_json: str | None = None
        for block in blocks:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(LLMToolCall(id=block.id, name=block.name, arguments=block.input))
                if is_structured_output and block.name == _STRUCTURED_OUTPUT_TOOL_NAME:
                    structured_json = json.dumps(block.input)
        if structured_json is not None:
            return structured_json, tool_calls
        return ("\n".join(text_parts) or None), tool_calls

    async def health_check(self) -> ProviderHealth:
        started = time.monotonic()
        try:
            async for _ in self._client.models.list(limit=1):
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
        if isinstance(exc, (BadRequestError, UnprocessableEntityError)):
            return ProviderInvalidRequestError(str(exc))
        if isinstance(exc, APIError):
            return ProviderUnavailableError(str(exc))
        return ProviderError(f"{type(exc).__name__}: {exc}")
