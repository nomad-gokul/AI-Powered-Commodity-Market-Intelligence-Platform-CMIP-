"""Unit tests for OllamaProvider against a mocked httpx.AsyncClient - no
real network calls, no real Ollama instance required. Implemented for
real but unverified against a live Ollama server in this environment
(see docs/ARCHITECTURE.md)."""

from unittest.mock import AsyncMock

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
from app.ai.providers.base import LLMRequest, LLMToolDefinition
from app.ai.providers.ollama_provider import OllamaProvider


def _fake_httpx_response(json_body: dict[str, object], status_code: int = 200) -> httpx.Response:
    request = httpx.Request("POST", "http://localhost:11434/api/chat")
    return httpx.Response(status_code=status_code, json=json_body, request=request)


@pytest.fixture
def provider() -> OllamaProvider:
    return OllamaProvider(base_url="http://localhost:11434")


class TestGenerate:
    async def test_returns_normalized_response(
        self, provider: OllamaProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        body = {
            "message": {"role": "assistant", "content": "hi there"},
            "done": True,
            "done_reason": "stop",
            "prompt_eval_count": 7,
            "eval_count": 3,
        }
        post = AsyncMock(return_value=_fake_httpx_response(body))
        monkeypatch.setattr(provider._client, "post", post)

        response = await provider.generate(LLMRequest(model="llama3.1", user_prompt="hi"))

        assert response.content == "hi there"
        assert response.provider == "ollama"
        assert response.usage.prompt_tokens == 7
        assert response.usage.completion_tokens == 3
        assert response.finish_reason == "stop"

    async def test_parses_tool_calls(
        self, provider: OllamaProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        body = {
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"function": {"name": "lookup", "arguments": {"q": "wheat"}}}],
            },
            "done": True,
            "prompt_eval_count": 5,
            "eval_count": 2,
        }
        post = AsyncMock(return_value=_fake_httpx_response(body))
        monkeypatch.setattr(provider._client, "post", post)

        response = await provider.generate(LLMRequest(model="llama3.1", user_prompt="hi"))

        assert len(response.tool_calls) == 1
        assert response.tool_calls[0].name == "lookup"
        assert response.tool_calls[0].arguments == {"q": "wheat"}

    async def test_sets_format_from_response_format(
        self, provider: OllamaProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        body = {
            "message": {"content": "{}"},
            "done": True,
            "prompt_eval_count": 1,
            "eval_count": 1,
        }
        post = AsyncMock(return_value=_fake_httpx_response(body))
        monkeypatch.setattr(provider._client, "post", post)
        schema = {"title": "Thing", "type": "object"}

        request = LLMRequest(model="llama3.1", user_prompt="hi", response_format=schema)
        await provider.generate(request)

        assert post.await_args.kwargs["json"]["format"] == schema

    async def test_forwards_max_tokens_and_tools(
        self, provider: OllamaProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        body = {
            "message": {"content": "ok"},
            "done": True,
            "prompt_eval_count": 1,
            "eval_count": 1,
        }
        post = AsyncMock(return_value=_fake_httpx_response(body))
        monkeypatch.setattr(provider._client, "post", post)

        request = LLMRequest(
            model="llama3.1",
            user_prompt="hi",
            max_tokens=128,
            tools=[LLMToolDefinition(name="lookup", description="look things up", parameters={})],
        )
        await provider.generate(request)

        payload = post.await_args.kwargs["json"]
        assert payload["options"]["num_predict"] == 128
        assert payload["tools"][0]["function"]["name"] == "lookup"

    def test_capabilities_reflects_ollama_feature_set(self, provider: OllamaProvider) -> None:
        assert provider.name == "ollama"
        assert provider.capabilities.supports_function_calling is False


class TestErrorTranslation:
    async def test_timeout_is_translated(
        self, provider: OllamaProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            provider._client, "post", AsyncMock(side_effect=httpx.ConnectTimeout("timed out"))
        )
        with pytest.raises(ProviderTimeoutError):
            await provider.generate(LLMRequest(model="m", user_prompt="hi"))

    async def test_auth_error_status_is_translated(
        self, provider: OllamaProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            provider._client, "post", AsyncMock(return_value=_fake_httpx_response({}, 401))
        )
        with pytest.raises(ProviderAuthError):
            await provider.generate(LLMRequest(model="m", user_prompt="hi"))

    async def test_generic_transport_error_is_translated_as_unavailable(
        self, provider: OllamaProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            provider._client, "post", AsyncMock(side_effect=httpx.ConnectError("refused"))
        )
        with pytest.raises(ProviderUnavailableError):
            await provider.generate(LLMRequest(model="m", user_prompt="hi"))

    async def test_unrecognized_exception_falls_back_to_generic_provider_error(
        self, provider: OllamaProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            provider._client, "post", AsyncMock(side_effect=RuntimeError("unexpected"))
        )
        with pytest.raises(ProviderError):
            await provider.generate(LLMRequest(model="m", user_prompt="hi"))

    async def test_rate_limit_status_is_translated(
        self, provider: OllamaProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            provider._client, "post", AsyncMock(return_value=_fake_httpx_response({}, 429))
        )
        with pytest.raises(ProviderRateLimitError):
            await provider.generate(LLMRequest(model="m", user_prompt="hi"))

    async def test_bad_request_status_is_translated(
        self, provider: OllamaProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            provider._client, "post", AsyncMock(return_value=_fake_httpx_response({}, 400))
        )
        with pytest.raises(ProviderInvalidRequestError):
            await provider.generate(LLMRequest(model="m", user_prompt="hi"))

    async def test_server_error_status_is_translated_as_unavailable(
        self, provider: OllamaProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            provider._client, "post", AsyncMock(return_value=_fake_httpx_response({}, 503))
        )
        with pytest.raises(ProviderUnavailableError):
            await provider.generate(LLMRequest(model="m", user_prompt="hi"))


class TestHealthCheck:
    async def test_healthy_when_tags_endpoint_succeeds(
        self, provider: OllamaProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        request = httpx.Request("GET", "http://localhost:11434/api/tags")
        response = httpx.Response(status_code=200, json={"models": []}, request=request)
        monkeypatch.setattr(provider._client, "get", AsyncMock(return_value=response))

        health = await provider.health_check()
        assert health.healthy is True

    async def test_unhealthy_when_unreachable(
        self, provider: OllamaProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            provider._client, "get", AsyncMock(side_effect=httpx.ConnectError("refused"))
        )
        health = await provider.health_check()
        assert health.healthy is False
