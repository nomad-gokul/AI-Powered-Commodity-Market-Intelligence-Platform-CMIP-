"""Unit tests for the provider-agnostic request/response models."""

import pytest
from shared.ai_contracts import (
    LLMMessage,
    LLMRequest,
    LLMResponse,
    ProviderCapabilities,
    ProviderHealth,
)

from ai_service.providers.base import LLMProvider


class MinimalProvider(LLMProvider):
    """A concrete LLMProvider implementing only the required abstract
    methods, to exercise the base class's default stream() in isolation
    from any real vendor SDK."""

    @property
    def name(self) -> str:
        return "minimal"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities()

    async def generate(self, request: LLMRequest) -> LLMResponse:
        raise NotImplementedError

    async def health_check(self) -> ProviderHealth:
        return ProviderHealth(healthy=True)


class TestEffectiveMessages:
    def test_uses_explicit_messages_when_present(self) -> None:
        request = LLMRequest(
            model="m",
            system_prompt="ignored",
            user_prompt="ignored",
            messages=[LLMMessage(role="user", content="explicit")],
        )
        assert [m.content for m in request.effective_messages()] == ["explicit"]

    def test_builds_messages_from_system_and_user_prompt(self) -> None:
        request = LLMRequest(model="m", system_prompt="sys", user_prompt="usr")
        messages = request.effective_messages()
        assert [(m.role, m.content) for m in messages] == [("system", "sys"), ("user", "usr")]

    def test_omits_system_prompt_when_not_set(self) -> None:
        request = LLMRequest(model="m", user_prompt="usr")
        messages = request.effective_messages()
        assert [m.role for m in messages] == ["user"]

    def test_empty_request_has_no_messages(self) -> None:
        request = LLMRequest(model="m")
        assert request.effective_messages() == []


class TestProviderCapabilities:
    def test_defaults_are_conservative(self) -> None:
        caps = ProviderCapabilities()
        assert caps.supports_streaming is False
        assert caps.supports_tools is False
        assert caps.supports_json_schema is False
        assert caps.max_context == 0

    def test_is_frozen(self) -> None:
        caps = ProviderCapabilities(supports_streaming=True)
        try:
            caps.supports_streaming = False  # type: ignore[misc]
        except AttributeError:
            pass
        else:
            raise AssertionError("ProviderCapabilities should be immutable")


class TestDefaultStream:
    async def test_raises_not_implemented_for_a_provider_that_does_not_override_it(self) -> None:
        provider = MinimalProvider()
        with pytest.raises(NotImplementedError, match="minimal"):
            async for _ in provider.stream(LLMRequest(model="m", user_prompt="hi")):
                pass
