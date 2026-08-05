"""Unit tests for EmbeddingService: content-hash-guarded generation
against a stateful fake repository (create/update/list_by_sources chain
enough calls per item that a fake is less brittle than wiring individual
AsyncMock returns, the same rationale graph/test_query_service.py's
merge_nodes tests use) and a fake EmbeddingProvider."""

import uuid

import pytest
from shared.ai_contracts import ProviderHealth
from shared.ai_exceptions import ConfigurationError
from shared.embedding_contracts import EmbeddingRequest, EmbeddingResponse, EmbeddingUsage

from app.modules.retrieval.embedding_service import EmbeddableItem, EmbeddingService, content_hash
from app.modules.retrieval.models import EMBEDDING_DIMENSION, Embedding, EmbeddingSourceType

# No module-level `pytestmark = pytest.mark.asyncio`: asyncio_mode="auto"
# (backend/pyproject.toml) already marks async tests automatically, and
# this module - unlike most - has one genuinely synchronous test
# (TestConstruction, since ConfigurationError raises from __init__, before
# any await point), which the explicit mark would incorrectly tag too.


class _FakeEmbeddingProvider:
    def __init__(
        self, *, dimension: int = EMBEDDING_DIMENSION, model: str = "text-embedding-3-small"
    ) -> None:
        self._dimension = dimension
        self._model = model
        self.embed_calls: list[EmbeddingRequest] = []

    @property
    def name(self) -> str:
        return "fake"

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def model(self) -> str:
        return self._model

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        self.embed_calls.append(request)
        return EmbeddingResponse(
            vectors=[[0.1] * self._dimension for _ in request.texts],
            provider=self.name,
            model=request.model,
            dimension=self._dimension,
            usage=EmbeddingUsage(prompt_tokens=len(request.texts), total_tokens=len(request.texts)),
            latency_ms=1.0,
        )

    async def health_check(self) -> ProviderHealth:
        return ProviderHealth(healthy=True)


class _FakeEmbeddingRepository:
    """In-memory stand-in for EmbeddingRepository, keyed like the real
    table's unique constraint (source_type, source_id, provider, model)."""

    def __init__(self, seed: list[Embedding] | None = None) -> None:
        self._rows: dict[tuple[str, str, str], Embedding] = {
            (row.source_type.value, row.source_id, row.embedding_provider): row
            for row in (seed or [])
        }
        self.create_calls = 0
        self.update_calls = 0

    async def list_by_sources(
        self, *, source_type: str, source_ids: list[str], embedding_provider: str
    ) -> dict[str, Embedding]:
        return {
            row.source_id: row
            for (s_type, source_id, provider), row in self._rows.items()
            if s_type == source_type and source_id in source_ids and provider == embedding_provider
        }

    async def create(self, entity: Embedding) -> Embedding:
        self.create_calls += 1
        self._rows[(entity.source_type.value, entity.source_id, entity.embedding_provider)] = entity
        return entity

    async def update(self, entity: Embedding, **fields: object) -> Embedding:
        self.update_calls += 1
        for key, value in fields.items():
            setattr(entity, key, value)
        return entity


def _embedding(
    *,
    source_type: EmbeddingSourceType,
    source_id: str,
    provider: str = "fake",
    hash_: str = "old-hash",
) -> Embedding:
    return Embedding(
        id=uuid.uuid4(),
        source_type=source_type,
        source_id=source_id,
        embedding_provider=provider,
        embedding_model="text-embedding-3-small",
        embedding_dimension=EMBEDDING_DIMENSION,
        embedding_hash=hash_,
        embedding_vector=[0.0] * EMBEDDING_DIMENSION,
    )


class TestConstruction:
    def test_dimension_mismatch_fails_fast(self) -> None:
        repository = _FakeEmbeddingRepository()
        provider = _FakeEmbeddingProvider(dimension=768)
        with pytest.raises(ConfigurationError, match="768-dim"):
            EmbeddingService(repository=repository, provider=provider)  # type: ignore[arg-type]


class TestEnsureEmbedded:
    async def test_empty_input_returns_empty_list(self) -> None:
        service = EmbeddingService(
            repository=_FakeEmbeddingRepository(), provider=_FakeEmbeddingProvider()  # type: ignore[arg-type]
        )
        assert await service.ensure_embedded([]) == []

    async def test_embeds_new_item_and_persists_it(self) -> None:
        provider = _FakeEmbeddingProvider()
        repository = _FakeEmbeddingRepository()
        service = EmbeddingService(repository=repository, provider=provider)  # type: ignore[arg-type]

        item = EmbeddableItem(
            source_type=EmbeddingSourceType.DOCUMENT_CHUNK, source_id="chunk-1", text="hello world"
        )
        result = await service.ensure_embedded([item])

        assert len(result) == 1
        assert result[0].embedding_hash == content_hash("hello world")
        assert repository.create_calls == 1
        assert len(provider.embed_calls) == 1

    async def test_skips_regeneration_when_hash_unchanged(self) -> None:
        provider = _FakeEmbeddingProvider()
        text = "unchanged content"
        existing = _embedding(
            source_type=EmbeddingSourceType.DOCUMENT_CHUNK,
            source_id="chunk-1",
            hash_=content_hash(text),
        )
        repository = _FakeEmbeddingRepository(seed=[existing])
        service = EmbeddingService(repository=repository, provider=provider)  # type: ignore[arg-type]

        item = EmbeddableItem(
            source_type=EmbeddingSourceType.DOCUMENT_CHUNK, source_id="chunk-1", text=text
        )
        result = await service.ensure_embedded([item])

        assert result == [existing]
        assert provider.embed_calls == []
        assert repository.create_calls == 0
        assert repository.update_calls == 0

    async def test_regenerates_and_updates_in_place_when_hash_changed(self) -> None:
        provider = _FakeEmbeddingProvider()
        existing = _embedding(
            source_type=EmbeddingSourceType.DOCUMENT_CHUNK, source_id="chunk-1", hash_="stale-hash"
        )
        repository = _FakeEmbeddingRepository(seed=[existing])
        service = EmbeddingService(repository=repository, provider=provider)  # type: ignore[arg-type]

        item = EmbeddableItem(
            source_type=EmbeddingSourceType.DOCUMENT_CHUNK, source_id="chunk-1", text="new content"
        )
        result = await service.ensure_embedded([item])

        assert result[0].embedding_hash == content_hash("new content")
        assert repository.update_calls == 1
        assert repository.create_calls == 0

    async def test_mixed_batch_only_embeds_the_changed_items(self) -> None:
        provider = _FakeEmbeddingProvider()
        unchanged_text = "stable"
        unchanged = _embedding(
            source_type=EmbeddingSourceType.GRAPH_NODE,
            source_id="node-1",
            hash_=content_hash(unchanged_text),
        )
        repository = _FakeEmbeddingRepository(seed=[unchanged])
        service = EmbeddingService(repository=repository, provider=provider)  # type: ignore[arg-type]

        items = [
            EmbeddableItem(
                source_type=EmbeddingSourceType.GRAPH_NODE, source_id="node-1", text=unchanged_text
            ),
            EmbeddableItem(
                source_type=EmbeddingSourceType.GRAPH_NODE, source_id="node-2", text="brand new"
            ),
        ]
        result = await service.ensure_embedded(items)

        assert len(result) == 2
        assert len(provider.embed_calls[0].texts) == 1
        assert provider.embed_calls[0].texts == ["brand new"]

    async def test_handles_multiple_source_types_in_one_batch(self) -> None:
        provider = _FakeEmbeddingProvider()
        repository = _FakeEmbeddingRepository()
        service = EmbeddingService(repository=repository, provider=provider)  # type: ignore[arg-type]

        items = [
            EmbeddableItem(
                source_type=EmbeddingSourceType.DOCUMENT_CHUNK, source_id="chunk-1", text="a"
            ),
            EmbeddableItem(
                source_type=EmbeddingSourceType.CANONICAL_ENTITY,
                source_id="company:adani_ports_sez",
                text="Adani Ports SEZ",
            ),
        ]
        result = await service.ensure_embedded(items)

        assert {r.source_type for r in result} == {
            EmbeddingSourceType.DOCUMENT_CHUNK,
            EmbeddingSourceType.CANONICAL_ENTITY,
        }
