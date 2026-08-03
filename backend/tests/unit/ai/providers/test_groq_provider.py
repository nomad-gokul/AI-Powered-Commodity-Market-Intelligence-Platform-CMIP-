"""Unit tests for GroqProvider against a mocked AsyncGroq client - no real
network calls. The one real, credential-backed Groq test lives in
tests/integration/ai/test_groq_live.py."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import groq
import httpx
import pytest

from app.ai.exceptions import (
    ProviderAuthError,
    ProviderError,
    ProviderInvalidRequestError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from app.ai.providers.base import LLMMessage, LLMRequest, LLMToolDefinition
from app.ai.providers.groq_provider import GroqProvider

from ._fakes import FakeAsyncStream, fake_completion, fake_response, fake_stream_chunk


@pytest.fixture
def provider() -> GroqProvider:
    return GroqProvider(api_key="test-key")


class TestGenerate:
    async def test_returns_normalized_response(
        self, provider: GroqProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        create = AsyncMock(return_value=fake_completion(content="hi there"))
        monkeypatch.setattr(provider._client.chat.completions, "create", create)

        response = await provider.generate(
            LLMRequest(model="llama-3.3-70b-versatile", user_prompt="hi")
        )

        assert response.content == "hi there"
        assert response.provider == "groq"
        assert response.usage.total_tokens == 15
        assert response.finish_reason == "stop"
        create.assert_awaited_once()

    async def test_parses_tool_calls(
        self, provider: GroqProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        tool_call = SimpleNamespace(
            id="call_1", function=SimpleNamespace(name="lookup", arguments='{"q": "wheat"}')
        )
        create = AsyncMock(return_value=fake_completion(content=None, tool_calls=[tool_call]))
        monkeypatch.setattr(provider._client.chat.completions, "create", create)

        response = await provider.generate(
            LLMRequest(model="llama-3.3-70b-versatile", user_prompt="hi")
        )

        assert len(response.tool_calls) == 1
        assert response.tool_calls[0].name == "lookup"
        assert response.tool_calls[0].arguments == {"q": "wheat"}

    async def test_sets_json_schema_response_format_when_given(
        self, provider: GroqProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        create = AsyncMock(return_value=fake_completion())
        monkeypatch.setattr(provider._client.chat.completions, "create", create)

        schema = {"title": "Thing", "type": "object", "properties": {}}
        await provider.generate(
            LLMRequest(model="llama-3.3-70b-versatile", user_prompt="hi", response_format=schema)
        )

        kwargs = create.await_args.kwargs
        assert kwargs["response_format"]["type"] == "json_schema"
        assert kwargs["response_format"]["json_schema"]["name"] == "Thing"

    async def test_raw_response_is_excluded_from_model_dump(
        self, provider: GroqProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        create = AsyncMock(return_value=fake_completion())
        monkeypatch.setattr(provider._client.chat.completions, "create", create)

        response = await provider.generate(LLMRequest(model="m", user_prompt="hi"))

        assert "raw_response" not in response.model_dump()

    async def test_forwards_max_tokens_and_tools_and_tool_messages(
        self, provider: GroqProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        create = AsyncMock(return_value=fake_completion())
        monkeypatch.setattr(provider._client.chat.completions, "create", create)

        request = LLMRequest(
            model="m",
            max_tokens=64,
            messages=[
                LLMMessage(role="user", content="look it up"),
                LLMMessage(role="tool", tool_call_id="call_1", name="lookup", content="5.2"),
            ],
            tools=[LLMToolDefinition(name="lookup", description="look things up", parameters={})],
        )
        await provider.generate(request)

        kwargs = create.await_args.kwargs
        assert kwargs["max_tokens"] == 64
        assert kwargs["tools"][0]["function"]["name"] == "lookup"
        tool_message = kwargs["messages"][1]
        assert tool_message["tool_call_id"] == "call_1"
        assert tool_message["name"] == "lookup"


class TestStreaming:
    async def test_yields_deltas_from_stream(
        self, provider: GroqProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stream = FakeAsyncStream(
            [fake_stream_chunk(delta="Hel"), fake_stream_chunk(delta="lo", finish_reason="stop")]
        )
        create = AsyncMock(return_value=stream)
        monkeypatch.setattr(provider._client.chat.completions, "create", create)

        chunks = [chunk async for chunk in provider.stream(LLMRequest(model="m", user_prompt="hi"))]

        assert [c.delta for c in chunks] == ["Hel", "lo"]
        assert chunks[-1].finish_reason == "stop"

    async def test_skips_chunks_with_no_choices(
        self, provider: GroqProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        empty_chunk = SimpleNamespace(choices=[])
        stream = FakeAsyncStream([empty_chunk, fake_stream_chunk(delta="ok")])
        monkeypatch.setattr(
            provider._client.chat.completions, "create", AsyncMock(return_value=stream)
        )

        chunks = [chunk async for chunk in provider.stream(LLMRequest(model="m", user_prompt="hi"))]

        assert [c.delta for c in chunks] == ["ok"]

    async def test_stream_translates_provider_errors(
        self, provider: GroqProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        create = AsyncMock(
            side_effect=groq.RateLimitError("limited", response=fake_response(429), body=None)
        )
        monkeypatch.setattr(provider._client.chat.completions, "create", create)

        with pytest.raises(ProviderRateLimitError):
            async for _ in provider.stream(LLMRequest(model="m", user_prompt="hi")):
                pass


class TestErrorTranslation:
    async def test_rate_limit_error_is_translated(
        self, provider: GroqProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        create = AsyncMock(
            side_effect=groq.RateLimitError("rate limited", response=fake_response(429), body=None)
        )
        monkeypatch.setattr(provider._client.chat.completions, "create", create)

        with pytest.raises(ProviderRateLimitError):
            await provider.generate(LLMRequest(model="m", user_prompt="hi"))

    async def test_authentication_error_is_translated(
        self, provider: GroqProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        create = AsyncMock(
            side_effect=groq.AuthenticationError("bad key", response=fake_response(401), body=None)
        )
        monkeypatch.setattr(provider._client.chat.completions, "create", create)

        with pytest.raises(ProviderAuthError):
            await provider.generate(LLMRequest(model="m", user_prompt="hi"))

    async def test_bad_request_error_is_translated(
        self, provider: GroqProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        create = AsyncMock(
            side_effect=groq.BadRequestError("bad request", response=fake_response(400), body=None)
        )
        monkeypatch.setattr(provider._client.chat.completions, "create", create)

        with pytest.raises(ProviderInvalidRequestError):
            await provider.generate(LLMRequest(model="m", user_prompt="hi"))

    async def test_timeout_error_is_translated(
        self, provider: GroqProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        create = AsyncMock(
            side_effect=groq.APITimeoutError(request=httpx.Request("POST", "http://test"))
        )
        monkeypatch.setattr(provider._client.chat.completions, "create", create)

        with pytest.raises(ProviderTimeoutError):
            await provider.generate(LLMRequest(model="m", user_prompt="hi"))

    async def test_connection_error_is_translated(
        self, provider: GroqProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        create = AsyncMock(
            side_effect=groq.APIConnectionError(
                message="unreachable", request=httpx.Request("POST", "http://test")
            )
        )
        monkeypatch.setattr(provider._client.chat.completions, "create", create)

        with pytest.raises(ProviderUnavailableError):
            await provider.generate(LLMRequest(model="m", user_prompt="hi"))

    async def test_generic_server_error_is_translated_as_unavailable(
        self, provider: GroqProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        create = AsyncMock(
            side_effect=groq.InternalServerError("down", response=fake_response(500), body=None)
        )
        monkeypatch.setattr(provider._client.chat.completions, "create", create)

        with pytest.raises(ProviderUnavailableError):
            await provider.generate(LLMRequest(model="m", user_prompt="hi"))

    async def test_unrecognized_exception_falls_back_to_generic_provider_error(
        self, provider: GroqProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        create = AsyncMock(side_effect=RuntimeError("something unexpected"))
        monkeypatch.setattr(provider._client.chat.completions, "create", create)

        with pytest.raises(ProviderError):
            await provider.generate(LLMRequest(model="m", user_prompt="hi"))


class TestHealthCheck:
    async def test_healthy_when_models_list_succeeds(
        self, provider: GroqProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(provider._client.models, "list", AsyncMock(return_value=None))
        health = await provider.health_check()
        assert health.healthy is True

    async def test_unhealthy_when_models_list_raises(
        self, provider: GroqProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            provider._client.models, "list", AsyncMock(side_effect=RuntimeError("down"))
        )
        health = await provider.health_check()
        assert health.healthy is False
        assert "down" in health.detail
