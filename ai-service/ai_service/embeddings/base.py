"""EmbeddingProvider: the single abstraction every embedding vendor
integration implements.

Mirrors ai_service.providers.base.LLMProvider exactly, for the same
reason: everything above this layer (backend's EmbeddingService) talks to
`EmbeddingProvider.embed()` and `.dimension` only, never to a vendor SDK
type directly, never branching on `if provider.name == "openai"`. Adding a
new embedding provider means writing one new class in this package, never
touching a caller.
"""

from abc import ABC, abstractmethod

from shared.ai_contracts import ProviderHealth
from shared.embedding_contracts import EmbeddingRequest, EmbeddingResponse


class EmbeddingProvider(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def dimension(self) -> int:
        """The fixed vector width this provider's configured model
        produces. backend's EmbeddingService checks this against the
        migrated `embeddings.embedding_vector` column width before the
        first write - see ai_service.embeddings.models' module docstring
        for why the column width is fixed at migration time."""
        ...

    @property
    @abstractmethod
    def model(self) -> str:
        """The model id this provider instance is bound to. Unlike
        LLMProvider (one instance serves whatever model a caller's
        LLMRequest names), one EmbeddingProvider instance is bound to
        exactly one model - dimension is fixed per instance, so the model
        can't vary call-to-call. Exposed so callers (EmbeddingService)
        never need their own provider-name-keyed lookup just to fill in
        EmbeddingRequest.model."""
        ...

    @abstractmethod
    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        """Embed a batch of texts, one vector per text in input order.

        Implementations translate vendor SDK exceptions into the
        shared.ai_exceptions.ProviderError taxonomy, exactly like
        LLMProvider.generate() - so callers make one provider-agnostic
        retry decision rather than knowing every vendor's exception types.
        """
        ...

    @abstractmethod
    async def health_check(self) -> ProviderHealth:
        """A cheap, low-latency call proving the provider is reachable and
        credentials are valid. Never a full embedding call, to avoid
        consuming API quota on every health probe."""
        ...
