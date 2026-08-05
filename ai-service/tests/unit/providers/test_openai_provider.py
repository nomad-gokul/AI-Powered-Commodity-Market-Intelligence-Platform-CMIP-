"""Unit tests for OpenAIProvider against a mocked AsyncOpenAI client - no
real network calls. Implemented for real but unverified against the live
OpenAI API in this environment (see docs/ARCHITECTURE.md)."""

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock

import openai
import pytest
from shared.ai_contracts import LLMRequest
from shared.ai_exceptions import ProviderAuthError, ProviderRateLimitError

from ai_service.providers.openai_provider import OpenAIProvider

from ._fakes import fake_completion, fake_response


@pytest.fixture
def provider() -> OpenAIProvider:
    return OpenAIProvider(api_key="test-key")


class TestGenerate:
    async def test_returns_normalized_response(
        self, provider: OpenAIProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        create = AsyncMock(return_value=fake_completion(content="hi there"))
        monkeypatch.setattr(provider._client.chat.completions, "create", create)

        response = await provider.generate(LLMRequest(model="gpt-4o-mini", user_prompt="hi"))

        assert response.content == "hi there"
        assert response.provider == "openai"
        assert response.usage.total_tokens == 15

    async def test_sets_json_schema_response_format_when_given(
        self, provider: OpenAIProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        create = AsyncMock(return_value=fake_completion())
        monkeypatch.setattr(provider._client.chat.completions, "create", create)

        schema = {"title": "Thing", "type": "object", "properties": {}}
        request = LLMRequest(model="gpt-4o-mini", user_prompt="hi", response_format=schema)
        await provider.generate(request)

        kwargs = create.await_args.kwargs
        assert kwargs["response_format"]["type"] == "json_schema"

    def test_capabilities_reflects_openai_feature_set(self, provider: OpenAIProvider) -> None:
        assert provider.capabilities.supports_json_schema is True
        assert provider.name == "openai"


class TestErrorTranslation:
    async def test_rate_limit_error_is_translated(
        self, provider: OpenAIProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        create = AsyncMock(
            side_effect=openai.RateLimitError("limited", response=fake_response(429), body=None)
        )
        monkeypatch.setattr(provider._client.chat.completions, "create", create)

        with pytest.raises(ProviderRateLimitError):
            await provider.generate(LLMRequest(model="m", user_prompt="hi"))

    async def test_authentication_error_is_translated(
        self, provider: OpenAIProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        create = AsyncMock(
            side_effect=openai.AuthenticationError(
                "bad key", response=fake_response(401), body=None
            )
        )
        monkeypatch.setattr(provider._client.chat.completions, "create", create)

        with pytest.raises(ProviderAuthError):
            await provider.generate(LLMRequest(model="m", user_prompt="hi"))


class TestHealthCheck:
    async def test_healthy_when_models_list_succeeds(
        self, provider: OpenAIProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def _list(*args: object, **kwargs: object) -> AsyncIterator[object]:
            yield object()

        monkeypatch.setattr(provider._client.models, "list", _list)
        health = await provider.health_check()
        assert health.healthy is True
        assert health.latency_ms is not None

    async def test_unhealthy_when_models_list_raises(
        self, provider: OpenAIProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def _list(*args: object, **kwargs: object) -> AsyncIterator[object]:
            raise RuntimeError("down")
            yield  # pragma: no cover - makes this an async generator

        monkeypatch.setattr(provider._client.models, "list", _list)
        health = await provider.health_check()
        assert health.healthy is False
        assert "down" in health.detail
