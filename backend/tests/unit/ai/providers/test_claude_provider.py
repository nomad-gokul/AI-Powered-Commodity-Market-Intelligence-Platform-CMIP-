"""Unit tests for ClaudeProvider against a mocked AsyncAnthropic client -
no real network calls. Implemented for real but unverified against the
live Anthropic API in this environment (see docs/ARCHITECTURE.md)."""

from collections.abc import AsyncIterator
from types import SimpleNamespace
from unittest.mock import AsyncMock

import anthropic
import httpx
import pytest

from app.ai.exceptions import (
    ProviderAuthError,
    ProviderInvalidRequestError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from app.ai.providers.base import LLMMessage, LLMRequest, LLMToolDefinition
from app.ai.providers.claude_provider import ClaudeProvider


def _fake_message(*, content: list[object], stop_reason: str = "end_turn") -> SimpleNamespace:
    usage = SimpleNamespace(input_tokens=8, output_tokens=4)
    return SimpleNamespace(content=content, usage=usage, stop_reason=stop_reason)


def _text_block(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


def _tool_use_block(*, id: str, name: str, input: dict[str, object]) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id=id, name=name, input=input)


def _fake_response(status_code: int) -> httpx.Response:
    return httpx.Response(status_code=status_code, request=httpx.Request("POST", "http://test"))


@pytest.fixture
def provider() -> ClaudeProvider:
    return ClaudeProvider(api_key="test-key")


class TestGenerate:
    async def test_returns_text_content(
        self, provider: ClaudeProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        create = AsyncMock(return_value=_fake_message(content=[_text_block("hello there")]))
        monkeypatch.setattr(provider._client.messages, "create", create)

        response = await provider.generate(LLMRequest(model="claude-sonnet-5", user_prompt="hi"))

        assert response.content == "hello there"
        assert response.provider == "claude"
        assert response.usage.prompt_tokens == 8
        assert response.usage.completion_tokens == 4

    async def test_system_prompt_is_split_out_of_messages(
        self, provider: ClaudeProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        create = AsyncMock(return_value=_fake_message(content=[_text_block("ok")]))
        monkeypatch.setattr(provider._client.messages, "create", create)

        await provider.generate(
            LLMRequest(model="m", system_prompt="be concise", user_prompt="hi")
        )

        kwargs = create.await_args.kwargs
        assert kwargs["system"] == "be concise"
        assert kwargs["messages"] == [{"role": "user", "content": "hi"}]

    async def test_structured_output_uses_forced_tool_call_and_returns_json_content(
        self, provider: ClaudeProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        tool_block = _tool_use_block(
            id="t1", name="emit_structured_response", input={"commodity": "wheat"}
        )
        create = AsyncMock(return_value=_fake_message(content=[tool_block]))
        monkeypatch.setattr(provider._client.messages, "create", create)

        schema = {"title": "Extraction", "type": "object", "properties": {}}
        response = await provider.generate(
            LLMRequest(model="m", user_prompt="hi", response_format=schema)
        )

        assert response.content == '{"commodity": "wheat"}'
        kwargs = create.await_args.kwargs
        assert kwargs["tool_choice"] == {"type": "tool", "name": "emit_structured_response"}

    async def test_tool_role_message_becomes_a_tool_result_content_block(
        self, provider: ClaudeProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        create = AsyncMock(return_value=_fake_message(content=[_text_block("ok")]))
        monkeypatch.setattr(provider._client.messages, "create", create)

        request = LLMRequest(
            model="m",
            messages=[
                LLMMessage(role="user", content="look it up"),
                LLMMessage(role="tool", tool_call_id="call_1", content='{"price": 5.2}'),
            ],
        )
        await provider.generate(request)

        kwargs = create.await_args.kwargs
        tool_message = kwargs["messages"][1]
        assert tool_message["content"][0]["type"] == "tool_result"
        assert tool_message["content"][0]["tool_use_id"] == "call_1"

    async def test_explicit_tools_are_forwarded_when_no_response_format(
        self, provider: ClaudeProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        create = AsyncMock(return_value=_fake_message(content=[_text_block("ok")]))
        monkeypatch.setattr(provider._client.messages, "create", create)

        request = LLMRequest(
            model="m",
            user_prompt="hi",
            tools=[LLMToolDefinition(name="lookup", description="look things up", parameters={})],
        )
        await provider.generate(request)

        kwargs = create.await_args.kwargs
        assert kwargs["tools"][0]["name"] == "lookup"

    def test_capabilities_reflects_claude_feature_set(self, provider: ClaudeProvider) -> None:
        assert provider.capabilities.supports_vision is True
        assert provider.name == "claude"


class TestErrorTranslation:
    async def test_rate_limit_error_is_translated(
        self, provider: ClaudeProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        create = AsyncMock(
            side_effect=anthropic.RateLimitError(
                "limited", response=_fake_response(429), body=None
            )
        )
        monkeypatch.setattr(provider._client.messages, "create", create)

        with pytest.raises(ProviderRateLimitError):
            await provider.generate(LLMRequest(model="m", user_prompt="hi"))

    async def test_authentication_error_is_translated(
        self, provider: ClaudeProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        create = AsyncMock(
            side_effect=anthropic.AuthenticationError(
                "bad key", response=_fake_response(401), body=None
            )
        )
        monkeypatch.setattr(provider._client.messages, "create", create)

        with pytest.raises(ProviderAuthError):
            await provider.generate(LLMRequest(model="m", user_prompt="hi"))

    async def test_timeout_error_is_translated(
        self, provider: ClaudeProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        create = AsyncMock(
            side_effect=anthropic.APITimeoutError(request=httpx.Request("POST", "http://test"))
        )
        monkeypatch.setattr(provider._client.messages, "create", create)

        with pytest.raises(ProviderTimeoutError):
            await provider.generate(LLMRequest(model="m", user_prompt="hi"))

    async def test_connection_error_is_translated(
        self, provider: ClaudeProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        create = AsyncMock(
            side_effect=anthropic.APIConnectionError(
                message="unreachable", request=httpx.Request("POST", "http://test")
            )
        )
        monkeypatch.setattr(provider._client.messages, "create", create)

        with pytest.raises(ProviderUnavailableError):
            await provider.generate(LLMRequest(model="m", user_prompt="hi"))

    async def test_bad_request_error_is_translated(
        self, provider: ClaudeProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        create = AsyncMock(
            side_effect=anthropic.BadRequestError(
                "bad request", response=_fake_response(400), body=None
            )
        )
        monkeypatch.setattr(provider._client.messages, "create", create)

        with pytest.raises(ProviderInvalidRequestError):
            await provider.generate(LLMRequest(model="m", user_prompt="hi"))

    async def test_generic_server_error_is_translated_as_unavailable(
        self, provider: ClaudeProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        create = AsyncMock(
            side_effect=anthropic.InternalServerError(
                "down", response=_fake_response(500), body=None
            )
        )
        monkeypatch.setattr(provider._client.messages, "create", create)

        with pytest.raises(ProviderUnavailableError):
            await provider.generate(LLMRequest(model="m", user_prompt="hi"))

    async def test_unrecognized_exception_falls_back_to_generic_provider_error(
        self, provider: ClaudeProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.ai.exceptions import ProviderError

        create = AsyncMock(side_effect=RuntimeError("something unexpected"))
        monkeypatch.setattr(provider._client.messages, "create", create)

        with pytest.raises(ProviderError):
            await provider.generate(LLMRequest(model="m", user_prompt="hi"))


class TestHealthCheck:
    async def test_healthy_when_models_list_succeeds(
        self, provider: ClaudeProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def _list(*args: object, **kwargs: object) -> AsyncIterator[object]:
            yield object()

        monkeypatch.setattr(provider._client.models, "list", _list)
        health = await provider.health_check()
        assert health.healthy is True

    async def test_unhealthy_when_models_list_raises(
        self, provider: ClaudeProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def _raise(*args: object, **kwargs: object) -> AsyncIterator[object]:
            raise RuntimeError("down")
            yield  # pragma: no cover

        monkeypatch.setattr(provider._client.models, "list", _raise)
        health = await provider.health_check()
        assert health.healthy is False
