"""AI capability interfaces business modules depend on.

New in Pre-Phase 5 (AI Service Extraction) - additive, not a rewrite of
existing call sites. Business-module pipeline-construction code
(app.modules.extraction/.trust/.graph, app.worker.context) continues to
construct the concrete ai-service classes exactly as before; only
constructor parameter *type hints* may reference these Protocols instead
of the concrete class, satisfying "business modules talk to AI only
through interfaces" with zero change in runtime behavior.

`AgentEngine` already is an interface (an ABC in ai_service.engine.base
with SequentialEngine as its only implementation today) and needs no
Protocol here - it relocates as-is.

Phase 5 (Knowledge Retrieval Platform) adds EmbeddingProviderProtocol and
RerankerProtocol on the same additive basis, for the same reason:
backend.app.modules.retrieval constructs the concrete ai_service classes
directly; these Protocols exist so its constructors can type-hint against
an interface instead of the concrete implementation.
"""

from typing import Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel

from shared.ai_contracts import LLMRequest, LLMResponse, LLMUsage, ProviderHealth
from shared.embedding_contracts import EmbeddingRequest, EmbeddingResponse
from shared.prompt_contracts import PromptPackage
from shared.retrieval_contracts import RetrievalCandidate

T = TypeVar("T", bound=BaseModel)


@runtime_checkable
class LLMClientProtocol(Protocol):
    """What ai_service.client.llm_client.LLMClient provides: the spec's
    "AIClient" - send/receive a generation request, and report health.
    Retry policy, observability, and provider selection are implementation
    details behind this interface, not part of the contract callers rely
    on."""

    async def generate(
        self, request: LLMRequest, *, correlation_id: str | None = None
    ) -> LLMResponse: ...

    async def health_check(self) -> ProviderHealth: ...


@runtime_checkable
class StructuredOutputServiceProtocol(Protocol):
    """What ai_service.structured.service.StructuredOutputService
    provides: LLMResponse -> Pydantic validation -> typed object, with
    automatic retry-on-invalid."""

    async def generate_structured(
        self,
        request: LLMRequest,
        response_model: type[T],
        *,
        max_retries: int = 2,
        correlation_id: str | None = None,
    ) -> T: ...

    async def generate_structured_with_usage(
        self,
        request: LLMRequest,
        response_model: type[T],
        *,
        max_retries: int = 2,
        correlation_id: str | None = None,
    ) -> tuple[T, LLMUsage]: ...


@runtime_checkable
class PromptRegistryProtocol(Protocol):
    """What ai_service.prompts.registry.PromptRegistry provides: register,
    load, and search versioned PromptPackages."""

    def register(self, package: PromptPackage) -> None: ...

    def get(self, name: str, version: str | None = None) -> PromptPackage: ...

    def list_versions(self, name: str) -> list[str]: ...

    def search(
        self, *, tag: str | None = None, author: str | None = None
    ) -> list[PromptPackage]: ...


@runtime_checkable
class EmbeddingProviderProtocol(Protocol):
    """What ai_service.embeddings.base.EmbeddingProvider provides: text in,
    vectors out, plus health reporting - mirrors LLMClientProtocol's shape
    for the embedding side of ai-service."""

    @property
    def dimension(self) -> int: ...

    @property
    def model(self) -> str: ...

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse: ...

    async def health_check(self) -> ProviderHealth: ...


@runtime_checkable
class RerankerProtocol(Protocol):
    """What ai_service.retrieval.reranker.RerankerService provides: score a
    batch of candidates from their raw RerankSignals and return them
    sorted by final rerank_score descending."""

    def rerank(self, candidates: list[RetrievalCandidate]) -> list[RetrievalCandidate]: ...
