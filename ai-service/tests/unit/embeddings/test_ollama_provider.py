"""Unit tests for OllamaEmbeddingProvider against a mocked httpx.AsyncClient
- no real network calls, no real Ollama instance required. Implemented for
real but unverified against a live Ollama server in this environment (see
docs/ARCHITECTURE.md)."""

from unittest.mock import AsyncMock

import httpx
import pytest
from shared.ai_exceptions import (
    ProviderAuthError,
    ProviderError,
    ProviderInvalidRequestError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from shared.embedding_contracts import EmbeddingRequest

from ai_service.embeddings.ollama_provider import OllamaEmbeddingProvider


def _fake_httpx_response(json_body: dict[str, object], status_code: int = 200) -> httpx.Response:
    request = httpx.Request("POST", "http://localhost:11434/api/embed")
    return httpx.Response(status_code=status_code, json=json_body, request=request)


@pytest.fixture
def provider() -> OllamaEmbeddingProvider:
    return OllamaEmbeddingProvider(
        base_url="http://localhost:11434", model="nomic-embed-text", dimension=3
    )


class TestEmbed:
    async def test_returns_normalized_response(
        self, provider: OllamaEmbeddingProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        body = {"embeddings": [[0.1, 0.2, 0.3]], "prompt_eval_count": 4}
        post = AsyncMock(return_value=_fake_httpx_response(body))
        monkeypatch.setattr(provider._client, "post", post)

        response = await provider.embed(
            EmbeddingRequest(texts=["hello"], model="nomic-embed-text")
        )

        assert response.vectors == [[0.1, 0.2, 0.3]]
        assert response.provider == "ollama"
        assert response.usage.prompt_tokens == 4

    async def test_forwards_all_texts_as_batch_input(
        self, provider: OllamaEmbeddingProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        body = {"embeddings": [[0.1], [0.2]], "prompt_eval_count": 2}
        post = AsyncMock(return_value=_fake_httpx_response(body))
        monkeypatch.setattr(provider._client, "post", post)

        await provider.embed(EmbeddingRequest(texts=["a", "b"], model="nomic-embed-text"))

        assert post.await_args.kwargs["json"]["input"] == ["a", "b"]

    def test_name_dimension_and_model(self, provider: OllamaEmbeddingProvider) -> None:
        assert provider.name == "ollama"
        assert provider.dimension == 3
        assert provider.model == "nomic-embed-text"


class TestErrorTranslation:
    async def test_timeout_is_translated(
        self, provider: OllamaEmbeddingProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            provider._client, "post", AsyncMock(side_effect=httpx.ConnectTimeout("timed out"))
        )
        with pytest.raises(ProviderTimeoutError):
            await provider.embed(EmbeddingRequest(texts=["hi"], model="m"))

    async def test_auth_error_status_is_translated(
        self, provider: OllamaEmbeddingProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            provider._client, "post", AsyncMock(return_value=_fake_httpx_response({}, 401))
        )
        with pytest.raises(ProviderAuthError):
            await provider.embed(EmbeddingRequest(texts=["hi"], model="m"))

    async def test_rate_limit_status_is_translated(
        self, provider: OllamaEmbeddingProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            provider._client, "post", AsyncMock(return_value=_fake_httpx_response({}, 429))
        )
        with pytest.raises(ProviderRateLimitError):
            await provider.embed(EmbeddingRequest(texts=["hi"], model="m"))

    async def test_bad_request_status_is_translated(
        self, provider: OllamaEmbeddingProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            provider._client, "post", AsyncMock(return_value=_fake_httpx_response({}, 400))
        )
        with pytest.raises(ProviderInvalidRequestError):
            await provider.embed(EmbeddingRequest(texts=["hi"], model="m"))

    async def test_server_error_status_is_translated_as_unavailable(
        self, provider: OllamaEmbeddingProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            provider._client, "post", AsyncMock(return_value=_fake_httpx_response({}, 503))
        )
        with pytest.raises(ProviderUnavailableError):
            await provider.embed(EmbeddingRequest(texts=["hi"], model="m"))

    async def test_unrecognized_exception_falls_back_to_generic_provider_error(
        self, provider: OllamaEmbeddingProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            provider._client, "post", AsyncMock(side_effect=RuntimeError("unexpected"))
        )
        with pytest.raises(ProviderError):
            await provider.embed(EmbeddingRequest(texts=["hi"], model="m"))


class TestHealthCheck:
    async def test_healthy_when_tags_endpoint_succeeds(
        self, provider: OllamaEmbeddingProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        request = httpx.Request("GET", "http://localhost:11434/api/tags")
        response = httpx.Response(status_code=200, json={"models": []}, request=request)
        monkeypatch.setattr(provider._client, "get", AsyncMock(return_value=response))

        health = await provider.health_check()
        assert health.healthy is True

    async def test_unhealthy_when_unreachable(
        self, provider: OllamaEmbeddingProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            provider._client, "get", AsyncMock(side_effect=httpx.ConnectError("refused"))
        )
        health = await provider.health_check()
        assert health.healthy is False
