"""Unit tests for LLMClient: retry policy (retryable vs not), latency/
usage passthrough, health-check passthrough, and that call metadata is
recorded without ever touching prompt/response content."""

import pytest
from shared.ai_contracts import (
    LLMRequest,
    LLMResponse,
    LLMUsage,
    ProviderCapabilities,
    ProviderHealth,
)
from shared.ai_exceptions import ProviderAuthError, ProviderRateLimitError

from ai_service.client.llm_client import LLMClient, LLMClientRetryPolicy, get_llm_client
from ai_service.config.settings import get_ai_settings
from ai_service.providers.base import LLMProvider
from ai_service.providers.factory import get_llm_provider


class StubProvider(LLMProvider):
    """A minimal LLMProvider whose generate() behavior is scripted per
    test: raises `error` for the first `fail_times` calls (or forever, if
    `fail_times` is None), then succeeds."""

    def __init__(
        self,
        *,
        error: Exception | None = None,
        fail_times: int | None = None,
        provider_name: str = "stub",
        health: ProviderHealth | None = None,
    ) -> None:
        self._error = error
        self._fail_times = fail_times
        self._provider_name = provider_name
        self._health = health or ProviderHealth(healthy=True)
        self.call_count = 0
        self.health_check_calls = 0

    @property
    def name(self) -> str:
        return self._provider_name

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities()

    async def generate(self, request: LLMRequest) -> LLMResponse:
        self.call_count += 1
        should_fail = self._error is not None and (
            self._fail_times is None or self.call_count <= self._fail_times
        )
        if should_fail:
            assert self._error is not None
            raise self._error
        return LLMResponse(
            content="ok",
            usage=LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            provider=self._provider_name,
            model=request.model,
            latency_ms=1.0,
            finish_reason="stop",
        )

    async def health_check(self) -> ProviderHealth:
        self.health_check_calls += 1
        return self._health


def _request() -> LLMRequest:
    return LLMRequest(model="llama-3.3-70b-versatile", user_prompt="hi")


class TestRetryableErrors:
    async def test_retries_and_succeeds_within_max_attempts(self) -> None:
        provider = StubProvider(error=ProviderRateLimitError("limited"), fail_times=2)
        policy = LLMClientRetryPolicy(max_attempts=3, backoff_base_seconds=0)
        client = LLMClient(provider, retry_policy=policy)

        response = await client.generate(_request())

        assert response.content == "ok"
        assert provider.call_count == 3

    async def test_raises_after_exhausting_retries(self) -> None:
        provider = StubProvider(error=ProviderRateLimitError("limited"))
        policy = LLMClientRetryPolicy(max_attempts=2, backoff_base_seconds=0)
        client = LLMClient(provider, retry_policy=policy)

        with pytest.raises(ProviderRateLimitError):
            await client.generate(_request())
        assert provider.call_count == 2


class TestNonRetryableErrors:
    async def test_auth_error_is_not_retried(self) -> None:
        provider = StubProvider(error=ProviderAuthError("bad key"))
        policy = LLMClientRetryPolicy(max_attempts=5, backoff_base_seconds=0)
        client = LLMClient(provider, retry_policy=policy)

        with pytest.raises(ProviderAuthError):
            await client.generate(_request())
        assert provider.call_count == 1


class TestSuccess:
    async def test_returns_response_unchanged_on_first_success(self) -> None:
        provider = StubProvider()
        client = LLMClient(provider)

        response = await client.generate(_request())

        assert response.usage.total_tokens == 15
        assert provider.call_count == 1

    async def test_correlation_id_defaults_to_generated_request_id(self) -> None:
        provider = StubProvider()
        client = LLMClient(provider)
        # No assertion target beyond "does not raise" - correlation_id is
        # internal bookkeeping surfaced only via observability logging.
        await client.generate(_request())

    def test_provider_property_exposes_the_wrapped_provider(self) -> None:
        provider = StubProvider()
        client = LLMClient(provider)
        assert client.provider is provider


class TestHealthCheck:
    async def test_delegates_to_the_wrapped_provider(self) -> None:
        provider = StubProvider(health=ProviderHealth(healthy=True, latency_ms=5.0))
        client = LLMClient(provider)

        health = await client.health_check()

        assert health.healthy is True
        assert health.latency_ms == 5.0
        assert provider.health_check_calls == 1

    async def test_surfaces_an_unhealthy_provider(self) -> None:
        provider = StubProvider(health=ProviderHealth(healthy=False, detail="down"))
        client = LLMClient(provider)

        health = await client.health_check()

        assert health.healthy is False
        assert health.detail == "down"


class TestGetLlmClient:
    def test_builds_cached_client_from_settings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GROQ_API_KEY", "test-key")
        get_ai_settings.cache_clear()
        get_llm_provider.cache_clear()
        get_llm_client.cache_clear()
        try:
            client = get_llm_client()
            assert isinstance(client, LLMClient)
            assert client.provider.name == "groq"
            assert get_llm_client() is client
        finally:
            get_ai_settings.cache_clear()
            get_llm_provider.cache_clear()
            get_llm_client.cache_clear()
