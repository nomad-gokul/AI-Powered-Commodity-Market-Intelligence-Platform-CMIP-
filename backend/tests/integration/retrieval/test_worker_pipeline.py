"""End-to-end test of Phase 5's embedding-generation worker task
(app/worker/tasks.py's generate_embeddings_task), called directly against
real Postgres - same pattern graph/test_worker_pipeline.py established for
run_graph_rebuild (AsyncSessionLocal directly, not db_session's fixture,
so cleanup here is explicit).

No real embedding provider is configured in this environment - the
graceful-skip path is exercised for real (ctx["embedding_provider"] is
genuinely None via build_worker_context()), and the actual-embedding path
is exercised against a real Postgres/pgvector round trip with a fake
embedding provider standing in for the real vendor API call, the same
"real DB, fake external vendor" pattern this codebase already uses for
OCR/S3 (see docs/ARCHITECTURE.md).
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from shared.ai_contracts import ProviderHealth
from shared.embedding_contracts import EmbeddingRequest, EmbeddingResponse, EmbeddingUsage
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.modules.documents.models import Document, DocumentChunk, StorageProviderKind
from app.modules.retrieval.models import Embedding, EmbeddingSourceType
from app.worker.context import build_worker_context
from app.worker.tasks import generate_embeddings_task

pytestmark = pytest.mark.asyncio


class _FakeEmbeddingProvider:
    def __init__(self, *, dimension: int = 1536) -> None:
        self._dimension = dimension

    @property
    def name(self) -> str:
        return "fake"

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def model(self) -> str:
        return "fake-model"

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
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


@asynccontextmanager
async def _document_with_chunks(chunk_texts: list[str]) -> AsyncIterator[Document]:
    async with AsyncSessionLocal() as session:
        document = Document(
            filename=f"{uuid.uuid4().hex}.pdf",
            original_filename="report.pdf",
            extension=".pdf",
            mime_type="application/pdf",
            file_size=100,
            sha256_hash=uuid.uuid4().hex + "0" * 32,
            storage_provider=StorageProviderKind.LOCAL,
            storage_key=f"{uuid.uuid4().hex}.pdf",
        )
        session.add(document)
        await session.flush()
        for index, text in enumerate(chunk_texts):
            session.add(
                DocumentChunk(
                    document_id=document.id,
                    chunk_index=index,
                    page_number=1,
                    text=text,
                    token_count=len(text.split()),
                    metadata_json={},
                )
            )
        await session.commit()
        document_id = document.id

    try:
        async with AsyncSessionLocal() as session:
            yield await session.get(Document, document_id)
    finally:
        async with AsyncSessionLocal() as session:
            await session.execute(
                delete(Embedding).where(
                    Embedding.source_type == EmbeddingSourceType.DOCUMENT_CHUNK
                )
            )
            await session.execute(
                delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
            )
            await session.execute(delete(Document).where(Document.id == document_id))
            await session.commit()


class TestGracefulDegradation:
    async def test_skips_without_raising_when_no_provider_is_configured(self) -> None:
        """build_worker_context() itself, unmodified, in this real
        environment - confirms the actual deployed degradation path, not
        a simulated one."""
        ctx = build_worker_context()
        assert ctx["embedding_provider"] is None

        async with _document_with_chunks(["Some real chunk text."]) as document:
            await generate_embeddings_task(ctx, document_id=str(document.id))

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Embedding).where(Embedding.source_type == EmbeddingSourceType.DOCUMENT_CHUNK)
            )
            assert result.scalars().first() is None


class TestEmbedsDocumentChunks:
    async def test_embeds_and_persists_real_rows_for_each_chunk(self) -> None:
        ctx = {"embedding_provider": _FakeEmbeddingProvider()}

        async with _document_with_chunks(["First chunk text.", "Second chunk text."]) as document:
            await generate_embeddings_task(ctx, document_id=str(document.id))

            async with AsyncSessionLocal() as session:
                chunks_result = await session.execute(
                    select(DocumentChunk).where(DocumentChunk.document_id == document.id)
                )
                chunk_ids = {str(c.id) for c in chunks_result.scalars().all()}

                embeddings_result = await session.execute(
                    select(Embedding).where(
                        Embedding.source_type == EmbeddingSourceType.DOCUMENT_CHUNK,
                        Embedding.source_id.in_(chunk_ids),
                    )
                )
                embeddings = embeddings_result.scalars().all()
                assert {e.source_id for e in embeddings} == chunk_ids
                assert all(e.embedding_provider == "fake" for e in embeddings)

    async def test_empty_chunk_text_is_not_embedded(self) -> None:
        ctx = {"embedding_provider": _FakeEmbeddingProvider()}

        async with _document_with_chunks(["", "  ", "real content here"]) as document:
            await generate_embeddings_task(ctx, document_id=str(document.id))

            async with AsyncSessionLocal() as session:
                chunks_result = await session.execute(
                    select(DocumentChunk).where(DocumentChunk.document_id == document.id)
                )
                real_chunk = next(
                    c for c in chunks_result.scalars().all() if c.text == "real content here"
                )
                embeddings_result = await session.execute(
                    select(Embedding).where(
                        Embedding.source_type == EmbeddingSourceType.DOCUMENT_CHUNK
                    )
                )
                embeddings = embeddings_result.scalars().all()
                assert {e.source_id for e in embeddings} == {str(real_chunk.id)}

    async def test_rerunning_with_unchanged_content_does_not_duplicate_rows(self) -> None:
        ctx = {"embedding_provider": _FakeEmbeddingProvider()}

        async with _document_with_chunks(["Stable content."]) as document:
            await generate_embeddings_task(ctx, document_id=str(document.id))
            await generate_embeddings_task(ctx, document_id=str(document.id))

            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(Embedding).where(
                        Embedding.source_type == EmbeddingSourceType.DOCUMENT_CHUNK
                    )
                )
                assert len(result.scalars().all()) == 1
