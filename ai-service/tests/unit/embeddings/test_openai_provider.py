"""Unit tests for OpenAIEmbeddingProvider against a mocked AsyncOpenAI
client - no real network calls. Implemented for real but unverified
against the live OpenAI API in this environment (see docs/ARCHITECTURE.md).
"""

from collections.abc import AsyncIterator
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import openai
import pytest
from shared.ai_exceptions import ProviderAuthError, ProviderRateLimitError
from shared.embedding_contracts import EmbeddingRequest

from ai_service.embeddings.openai_provider import OpenAIEmbeddingProvider


def _fake_response(status_code: int) -> httpx.Response:
    return httpx.Response(status_code=status_code, request=httpx.Request("POST", "http://test"))


def _fake_embedding_response(vectors: list[list[float]], *, model: str = "m") -> SimpleNamespace:
    data = [SimpleNamespace(embedding=v, index=i) for i, v in enumerate(vectors)]
    usage = SimpleNamespace(prompt_tokens=10, total_tokens=10)
    return SimpleNamespace(data=data, model=model, usage=usage)


@pytest.fixture
def provider() -> OpenAIEmbeddingProvider:
    return OpenAIEmbeddingProvider(
        api_key="test-key", model="text-embedding-3-small", dimension=3
    )


class TestEmbed:
    async def test_returns_normalized_response(
        self, provider: OpenAIEmbeddingProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        create = AsyncMock(return_value=_fake_embedding_response([[0.1, 0.2, 0.3]]))
        monkeypatch.setattr(provider._client.embeddings, "create", create)

        response = await provider.embed(
            EmbeddingRequest(texts=["hello"], model="text-embedding-3-small")
        )

        assert response.vectors == [[0.1, 0.2, 0.3]]
        assert response.provider == "openai"
        assert response.dimension == 3
        assert response.usage.total_tokens == 10

    async def test_preserves_input_order_by_response_index(
        self, provider: OpenAIEmbeddingProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Return items out of order to prove the provider re-sorts by index.
        data = [
            SimpleNamespace(embedding=[0.9], index=1),
            SimpleNamespace(embedding=[0.1], index=0),
        ]
        response = SimpleNamespace(
            data=data, model="m", usage=SimpleNamespace(prompt_tokens=1, total_tokens=1)
        )
        create = AsyncMock(return_value=response)
        monkeypatch.setattr(provider._client.embeddings, "create", create)

        result = await provider.embed(EmbeddingRequest(texts=["a", "b"], model="m"))

        assert result.vectors == [[0.1], [0.9]]

    def test_name_dimension_and_model(self, provider: OpenAIEmbeddingProvider) -> None:
        assert provider.name == "openai"
        assert provider.dimension == 3
        assert provider.model == "text-embedding-3-small"


class TestErrorTranslation:
    async def test_rate_limit_error_is_translated(
        self, provider: OpenAIEmbeddingProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        create = AsyncMock(
            side_effect=openai.RateLimitError("limited", response=_fake_response(429), body=None)
        )
        monkeypatch.setattr(provider._client.embeddings, "create", create)

        with pytest.raises(ProviderRateLimitError):
            await provider.embed(EmbeddingRequest(texts=["hi"], model="m"))

    async def test_authentication_error_is_translated(
        self, provider: OpenAIEmbeddingProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        create = AsyncMock(
            side_effect=openai.AuthenticationError(
                "bad key", response=_fake_response(401), body=None
            )
        )
        monkeypatch.setattr(provider._client.embeddings, "create", create)

        with pytest.raises(ProviderAuthError):
            await provider.embed(EmbeddingRequest(texts=["hi"], model="m"))


class TestHealthCheck:
    async def test_healthy_when_models_list_succeeds(
        self, provider: OpenAIEmbeddingProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def _list(*args: object, **kwargs: object) -> AsyncIterator[object]:
            yield object()

        monkeypatch.setattr(provider._client.models, "list", _list)
        health = await provider.health_check()
        assert health.healthy is True

    async def test_unhealthy_when_models_list_raises(
        self, provider: OpenAIEmbeddingProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def _list(*args: object, **kwargs: object) -> AsyncIterator[object]:
            raise RuntimeError("down")
            yield  # pragma: no cover - makes this an async generator

        monkeypatch.setattr(provider._client.models, "list", _list)
        health = await provider.health_check()
        assert health.healthy is False
