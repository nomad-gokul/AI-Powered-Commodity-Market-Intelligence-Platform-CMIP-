"""EmbeddingService: generates embeddings for document chunks, graph
nodes, graph edges, canonical entities, and ontology definitions - one
implementation for all five source types, content-hash-guarded so "never
regenerate identical embeddings" holds regardless of caller.

Calls ai-service's EmbeddingProvider directly (an in-process import, not
yet HTTP/gRPC/queue - see docs/ARCHITECTURE.md's Pre-Phase 5 section for
why that's the current transport and how a future swap would only change
how this one dependency is constructed, never this class's logic or its
callers).
"""

import hashlib
import time
import uuid
from dataclasses import dataclass

from ai_service.embeddings.base import EmbeddingProvider
from ai_service.observability.tracking import record_embedding_call
from shared.ai_exceptions import ConfigurationError
from shared.embedding_contracts import EmbeddingRequest

from app.core.metrics import embeddings_generated_total
from app.modules.retrieval.models import EMBEDDING_DIMENSION, Embedding, EmbeddingSourceType
from app.modules.retrieval.repository import EmbeddingRepository


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class EmbeddableItem:
    """One thing EmbeddingService can embed: a (source_type, source_id)
    pair plus the exact text its embedding should represent."""

    source_type: EmbeddingSourceType
    source_id: str
    text: str


class EmbeddingService:
    def __init__(self, *, repository: EmbeddingRepository, provider: EmbeddingProvider) -> None:
        self._repository = repository
        self._provider = provider
        if provider.dimension != EMBEDDING_DIMENSION:
            raise ConfigurationError(
                f"Configured embedding model {provider.model!r} produces "
                f"{provider.dimension}-dim vectors, but the "
                f"embeddings.embedding_vector column is fixed at {EMBEDDING_DIMENSION} "
                "dims. Either choose a matching-dimension model or run a migration to "
                "resize the column.",
                details={
                    "configured_dimension": provider.dimension,
                    "column_dimension": EMBEDDING_DIMENSION,
                },
            )

    async def ensure_embedded(self, items: list[EmbeddableItem]) -> list[Embedding]:
        """Embed every item in `items` whose content hash has changed (or
        that has never been embedded before), skip the rest, and return
        the current Embedding row for each item, in input order."""
        if not items:
            return []

        hashes = {item.source_id: content_hash(item.text) for item in items}
        existing_by_id = await self._load_existing(items)

        to_embed = [
            item
            for item in items
            if existing_by_id.get(item.source_id) is None
            or existing_by_id[item.source_id].embedding_hash != hashes[item.source_id]
        ]
        if to_embed:
            await self._embed_and_persist(to_embed, hashes, existing_by_id)

        return [
            existing_by_id[item.source_id] for item in items if item.source_id in existing_by_id
        ]

    async def _load_existing(self, items: list[EmbeddableItem]) -> dict[str, Embedding]:
        by_source_type: dict[EmbeddingSourceType, list[str]] = {}
        for item in items:
            by_source_type.setdefault(item.source_type, []).append(item.source_id)

        existing_by_id: dict[str, Embedding] = {}
        for source_type, source_ids in by_source_type.items():
            existing = await self._repository.list_by_sources(
                source_type=source_type.value,
                source_ids=source_ids,
                embedding_provider=self._provider.name,
            )
            existing_by_id.update(existing)
        return existing_by_id

    async def _embed_and_persist(
        self,
        to_embed: list[EmbeddableItem],
        hashes: dict[str, str],
        existing_by_id: dict[str, Embedding],
    ) -> None:
        started = time.monotonic()
        response = await self._provider.embed(
            EmbeddingRequest(texts=[item.text for item in to_embed], model=self._provider.model)
        )
        record_embedding_call(
            provider=response.provider,
            model=response.model,
            latency_ms=(time.monotonic() - started) * 1000,
            usage=response.usage,
            item_count=len(to_embed),
        )
        for item, vector in zip(to_embed, response.vectors, strict=True):
            embeddings_generated_total.labels(source_type=item.source_type.value).inc()
            existing = existing_by_id.get(item.source_id)
            if existing is not None:
                updated = await self._repository.update(
                    existing,
                    embedding_hash=hashes[item.source_id],
                    embedding_vector=vector,
                    embedding_dimension=response.dimension,
                )
                existing_by_id[item.source_id] = updated
            else:
                created = await self._repository.create(
                    Embedding(
                        id=uuid.uuid4(),
                        source_type=item.source_type,
                        source_id=item.source_id,
                        embedding_provider=response.provider,
                        embedding_model=response.model,
                        embedding_dimension=response.dimension,
                        embedding_hash=hashes[item.source_id],
                        embedding_vector=vector,
                    )
                )
                existing_by_id[item.source_id] = created
