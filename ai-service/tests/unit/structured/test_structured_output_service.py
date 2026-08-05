"""Unit tests for StructuredOutputService: validation, retry-with-
correction on invalid output, and giving up after max_retries."""

import pytest
from pydantic import BaseModel
from shared.ai_contracts import (
    LLMRequest,
    LLMResponse,
    LLMUsage,
    ProviderCapabilities,
    ProviderHealth,
)
from shared.ai_exceptions import StructuredOutputError

from ai_service.client.llm_client import LLMClient
from ai_service.providers.base import LLMProvider
from ai_service.structured.service import StructuredOutputService


class ExtractedCommodity(BaseModel):
    name: str
    unit: str


class ScriptedProvider(LLMProvider):
    """Returns each entry in `responses` in order, one per generate() call."""

    def __init__(self, responses: list[str | None]) -> None:
        self._responses = list(responses)
        self.requests: list[LLMRequest] = []

    @property
    def name(self) -> str:
        return "scripted"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(supports_json_schema=True)

    async def generate(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        content = self._responses.pop(0)
        return LLMResponse(
            content=content,
            usage=LLMUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            provider=self.name,
            model=request.model,
            latency_ms=1.0,
            finish_reason="stop",
        )

    async def health_check(self) -> ProviderHealth:
        return ProviderHealth(healthy=True)


def _service(responses: list[str | None]) -> tuple[StructuredOutputService, ScriptedProvider]:
    provider = ScriptedProvider(responses)
    client = LLMClient(provider)
    return StructuredOutputService(client), provider


class TestValidation:
    async def test_returns_typed_object_on_valid_first_response(self) -> None:
        service, provider = _service(['{"name": "wheat", "unit": "MT"}'])

        result = await service.generate_structured(
            LLMRequest(model="m", user_prompt="extract"), ExtractedCommodity
        )

        assert result == ExtractedCommodity(name="wheat", unit="MT")
        assert len(provider.requests) == 1
        assert provider.requests[0].response_format is not None

    async def test_retries_after_invalid_json_and_succeeds(self) -> None:
        service, provider = _service(["not json", '{"name": "corn", "unit": "bu"}'])

        result = await service.generate_structured(
            LLMRequest(model="m", user_prompt="extract"), ExtractedCommodity, max_retries=2
        )

        assert result == ExtractedCommodity(name="corn", unit="bu")
        assert len(provider.requests) == 2

    async def test_retries_after_schema_mismatch_and_succeeds(self) -> None:
        service, provider = _service(
            ['{"name": "corn"}', '{"name": "corn", "unit": "bu"}']  # missing required field first
        )

        result = await service.generate_structured(
            LLMRequest(model="m", user_prompt="extract"), ExtractedCommodity, max_retries=2
        )

        assert result.unit == "bu"

    async def test_correction_message_includes_the_invalid_prior_response(self) -> None:
        service, provider = _service(["not json", '{"name": "corn", "unit": "bu"}'])

        await service.generate_structured(
            LLMRequest(model="m", user_prompt="extract"), ExtractedCommodity, max_retries=2
        )

        second_request_messages = provider.requests[1].messages
        assert any(
            m.role == "assistant" and m.content == "not json" for m in second_request_messages
        )

    async def test_raises_structured_output_error_after_exhausting_retries(self) -> None:
        service, _ = _service(["not json", "still not json"])

        with pytest.raises(StructuredOutputError):
            await service.generate_structured(
                LLMRequest(model="m", user_prompt="extract"), ExtractedCommodity, max_retries=1
            )

    async def test_none_content_is_treated_as_invalid_and_retried(self) -> None:
        service, provider = _service([None, '{"name": "soy", "unit": "bu"}'])

        result = await service.generate_structured(
            LLMRequest(model="m", user_prompt="extract"), ExtractedCommodity, max_retries=1
        )

        assert result.name == "soy"
        assert len(provider.requests) == 2
