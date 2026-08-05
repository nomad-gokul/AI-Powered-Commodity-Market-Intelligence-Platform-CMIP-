"""Shared implementation for vendors whose SDK exposes an OpenAI-shaped
`chat.completions.create(messages=..., model=...)` call returning a
ChatCompletion. Groq's SDK is a fork of openai-python and OpenAI's is the
original, so both request-building and response-parsing are identical;
only the concrete client type and exception classes differ per vendor.

This is intentionally private (leading underscore in the module name) - it
is not itself a registered provider, just shared plumbing for
GroqProvider and OpenAIProvider. Each of those still writes its own
class, capabilities, and name; nothing here is imported by callers of
ai_service.providers.
"""

import json
import time
from abc import abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from shared.ai_contracts import LLMRequest, LLMResponse, LLMStreamChunk, LLMToolCall, LLMUsage
from shared.ai_exceptions import (
    ProviderAuthError,
    ProviderError,
    ProviderInvalidRequestError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)

from ai_service.providers.base import LLMProvider


@dataclass(frozen=True, slots=True)
class SDKErrorMap:
    """The concrete exception classes a vendor's SDK raises, so this base
    class can translate them without importing every vendor SDK itself."""

    rate_limit: type[Exception]
    authentication: type[Exception]
    bad_request: type[Exception]
    unprocessable_entity: type[Exception]
    timeout: type[Exception]
    connection: type[Exception]
    api_error: type[Exception]


class ChatCompletionsCompatibleProvider(LLMProvider):
    def __init__(self, *, errors: SDKErrorMap) -> None:
        self._errors = errors

    @property
    @abstractmethod
    def _completions(self) -> Any:
        """The vendor client's `.chat.completions` resource. Typed `Any`
        deliberately: each vendor SDK's generated client type has its own
        precise (and very long) overload set for `.create()` that isn't
        worth re-declaring here - the shared request/response handling in
        this class is what's actually being tested and typed, not the
        third-party SDK's own signature."""
        ...

    def _build_messages(self, request: LLMRequest) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        for message in request.effective_messages():
            entry: dict[str, Any] = {"role": message.role, "content": message.content}
            if message.tool_call_id:
                entry["tool_call_id"] = message.tool_call_id
            if message.name:
                entry["name"] = message.name
            messages.append(entry)
        return messages

    def _build_kwargs(self, request: LLMRequest, *, stream: bool) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": request.model,
            "messages": self._build_messages(request),
            "temperature": request.temperature,
            "top_p": request.top_p,
            "stream": stream,
        }
        if request.max_tokens is not None:
            kwargs["max_tokens"] = request.max_tokens
        if request.tools:
            kwargs["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters,
                    },
                }
                for tool in request.tools
            ]
        if request.response_format is not None and self.capabilities.supports_json_schema:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": request.response_format.get("title", "structured_response"),
                    "schema": request.response_format,
                    "strict": True,
                },
            }
        return kwargs

    async def generate(self, request: LLMRequest) -> LLMResponse:
        started = time.monotonic()
        try:
            completion = await self._completions.create(**self._build_kwargs(request, stream=False))
        except Exception as exc:
            raise self._translate_error(exc) from exc
        latency_ms = (time.monotonic() - started) * 1000

        choice = completion.choices[0]
        raw_tool_calls = getattr(choice.message, "tool_calls", None) or []
        tool_calls = [
            LLMToolCall(
                id=call.id,
                name=call.function.name,
                arguments=json.loads(call.function.arguments or "{}"),
            )
            for call in raw_tool_calls
        ]
        usage = completion.usage
        return LLMResponse(
            content=choice.message.content,
            tool_calls=tool_calls,
            usage=LLMUsage(
                prompt_tokens=usage.prompt_tokens if usage else 0,
                completion_tokens=usage.completion_tokens if usage else 0,
                total_tokens=usage.total_tokens if usage else 0,
            ),
            provider=self.name,
            model=request.model,
            latency_ms=latency_ms,
            finish_reason=choice.finish_reason or "unknown",
            raw_response=completion,
        )

    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMStreamChunk]:
        try:
            kwargs = self._build_kwargs(request, stream=True)
            response_stream = await self._completions.create(**kwargs)
            async for chunk in response_stream:
                choice = chunk.choices[0] if chunk.choices else None
                if choice is None:
                    continue
                delta = getattr(choice.delta, "content", None) or ""
                yield LLMStreamChunk(delta=delta, finish_reason=choice.finish_reason)
        except Exception as exc:
            raise self._translate_error(exc) from exc

    def _translate_error(self, exc: Exception) -> ProviderError:
        e = self._errors
        if isinstance(exc, e.rate_limit):
            return ProviderRateLimitError(str(exc))
        if isinstance(exc, e.timeout):
            return ProviderTimeoutError(str(exc))
        if isinstance(exc, e.connection):
            return ProviderUnavailableError(str(exc))
        if isinstance(exc, e.authentication):
            return ProviderAuthError(str(exc))
        if isinstance(exc, (e.bad_request, e.unprocessable_entity)):
            return ProviderInvalidRequestError(str(exc))
        if isinstance(exc, e.api_error):
            return ProviderUnavailableError(str(exc))
        return ProviderError(f"{type(exc).__name__}: {exc}")
