"""Shared test doubles for extraction agent tests - not production code."""

from pydantic import BaseModel

from app.ai.providers.base import LLMRequest, LLMUsage


class ScriptedStructuredOutputService:
    """A StructuredOutputService double returning pre-scripted responses in
    order, one per call, and recording every request it was given - lets
    agent tests assert on prompt-building without a real LLMClient/
    LLMProvider stack (already covered by Phase 3.1's own test suite)."""

    def __init__(self, responses: list[tuple[BaseModel, LLMUsage]]) -> None:
        self._responses = list(responses)
        self.requests: list[LLMRequest] = []

    async def generate_structured_with_usage(
        self,
        request: LLMRequest,
        response_model: type[BaseModel],
        *,
        max_retries: int = 2,
        correlation_id: str | None = None,
    ) -> tuple[BaseModel, LLMUsage]:
        self.requests.append(request)
        return self._responses.pop(0)

    async def generate_structured(
        self,
        request: LLMRequest,
        response_model: type[BaseModel],
        *,
        max_retries: int = 2,
        correlation_id: str | None = None,
    ) -> BaseModel:
        result, _usage = await self.generate_structured_with_usage(
            request, response_model, max_retries=max_retries, correlation_id=correlation_id
        )
        return result
