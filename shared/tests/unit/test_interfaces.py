"""Unit tests for the new business-facing AI Protocols: a structurally
conforming stand-in satisfies each Protocol without inheriting from it,
mirroring how ai-service's concrete LLMClient/StructuredOutputService/
PromptRegistry classes satisfy them today without declaring so."""

from pydantic import BaseModel

from shared.ai_contracts import LLMRequest, LLMResponse, LLMUsage, ProviderHealth
from shared.embedding_contracts import EmbeddingRequest, EmbeddingResponse, EmbeddingUsage
from shared.interfaces import (
    EmbeddingProviderProtocol,
    LLMClientProtocol,
    PromptRegistryProtocol,
    RerankerProtocol,
    StructuredOutputServiceProtocol,
)
from shared.prompt_contracts import PromptPackage, PromptVersion
from shared.retrieval_contracts import RetrievalCandidate


class _Model(BaseModel):
    value: str


class _ConformingLLMClient:
    async def generate(
        self, request: LLMRequest, *, correlation_id: str | None = None
    ) -> LLMResponse:
        return LLMResponse(
            content="ok", usage=LLMUsage(), provider="fake", model="fake", latency_ms=0.0,
            finish_reason="stop",
        )

    async def health_check(self) -> ProviderHealth:
        return ProviderHealth(healthy=True)


class _ConformingStructuredOutputService:
    async def generate_structured(
        self, request: LLMRequest, response_model: type[_Model], *,
        max_retries: int = 2, correlation_id: str | None = None,
    ) -> _Model:
        return response_model(value="ok")

    async def generate_structured_with_usage(
        self, request: LLMRequest, response_model: type[_Model], *,
        max_retries: int = 2, correlation_id: str | None = None,
    ) -> tuple[_Model, LLMUsage]:
        return response_model(value="ok"), LLMUsage()


class _ConformingPromptRegistry:
    def register(self, package: PromptPackage) -> None: ...

    def get(self, name: str, version: str | None = None) -> PromptPackage:
        return PromptPackage(
            name=name, version=PromptVersion(major=1), system_prompt="s",
            user_prompt_template="u",
        )

    def list_versions(self, name: str) -> list[str]:
        return ["1.0"]

    def search(
        self, *, tag: str | None = None, author: str | None = None
    ) -> list[PromptPackage]:
        return []


class _ConformingEmbeddingProvider:
    @property
    def dimension(self) -> int:
        return 1536

    @property
    def model(self) -> str:
        return "fake-embedding-model"

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        return EmbeddingResponse(
            vectors=[[0.0] * 1536 for _ in request.texts],
            provider="fake",
            model=request.model,
            dimension=1536,
            usage=EmbeddingUsage(),
            latency_ms=0.0,
        )

    async def health_check(self) -> ProviderHealth:
        return ProviderHealth(healthy=True)


class _ConformingReranker:
    def rerank(self, candidates: list[RetrievalCandidate]) -> list[RetrievalCandidate]:
        return sorted(candidates, key=lambda c: c.score, reverse=True)


class TestProtocolConformance:
    def test_conforming_llm_client_satisfies_protocol(self) -> None:
        assert isinstance(_ConformingLLMClient(), LLMClientProtocol)

    def test_conforming_structured_output_service_satisfies_protocol(self) -> None:
        assert isinstance(_ConformingStructuredOutputService(), StructuredOutputServiceProtocol)

    def test_conforming_prompt_registry_satisfies_protocol(self) -> None:
        assert isinstance(_ConformingPromptRegistry(), PromptRegistryProtocol)

    def test_object_missing_health_check_does_not_satisfy_llm_client_protocol(self) -> None:
        class _Incomplete:
            async def generate(
                self, request: LLMRequest, *, correlation_id: str | None = None
            ) -> LLMResponse:
                raise NotImplementedError

        assert isinstance(_Incomplete(), LLMClientProtocol) is False

    def test_conforming_embedding_provider_satisfies_protocol(self) -> None:
        assert isinstance(_ConformingEmbeddingProvider(), EmbeddingProviderProtocol)

    def test_conforming_reranker_satisfies_protocol(self) -> None:
        assert isinstance(_ConformingReranker(), RerankerProtocol)

    def test_object_missing_rerank_does_not_satisfy_reranker_protocol(self) -> None:
        class _Incomplete:
            def some_other_method(self) -> None: ...

        assert isinstance(_Incomplete(), RerankerProtocol) is False
