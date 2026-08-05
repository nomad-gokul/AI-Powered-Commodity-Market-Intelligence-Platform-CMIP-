"""Real, credential-backed integration test against the live Groq API.

Skipped entirely if GROQ_API_KEY isn't set - this is the ONE provider with
a genuine live test in this environment; Claude/OpenAI/Ollama are
implemented for real against their official SDKs but unverified here (see
docs/ARCHITECTURE.md's provider testing strategy).
"""

import os

import pytest
from pydantic import BaseModel
from shared.ai_contracts import LLMRequest

from ai_service.client.llm_client import LLMClient
from ai_service.providers.groq_provider import GroqProvider
from ai_service.structured.service import StructuredOutputService

pytestmark = pytest.mark.skipif(
    not os.environ.get("GROQ_API_KEY"),
    reason="GROQ_API_KEY not set - skipping live Groq integration test",
)


class SimpleAnswer(BaseModel):
    answer: str


@pytest.fixture
def provider() -> GroqProvider:
    return GroqProvider(api_key=os.environ["GROQ_API_KEY"])


class TestGroqLiveGenerate:
    async def test_generate_returns_real_completion(self, provider: GroqProvider) -> None:
        response = await provider.generate(
            LLMRequest(
                model="llama-3.1-8b-instant",
                system_prompt="Reply with exactly one word.",
                user_prompt="Say 'hello'.",
                max_tokens=10,
            )
        )
        assert response.content
        assert response.provider == "groq"
        assert response.usage.total_tokens > 0
        assert response.latency_ms > 0

    async def test_health_check_reports_healthy(self, provider: GroqProvider) -> None:
        health = await provider.health_check()
        assert health.healthy is True


class TestGroqLiveStructuredOutput:
    async def test_structured_output_returns_valid_typed_object(
        self, provider: GroqProvider
    ) -> None:
        client = LLMClient(provider)
        service = StructuredOutputService(client)

        result = await service.generate_structured(
            LLMRequest(
                model="llama-3.1-8b-instant",
                system_prompt="Answer questions concisely.",
                user_prompt="What is the capital of France? Respond in the required JSON schema.",
            ),
            SimpleAnswer,
        )

        assert isinstance(result, SimpleAnswer)
        assert "paris" in result.answer.lower()
