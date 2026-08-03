"""Data access for documents, version history, processing jobs, and chunk
metadata."""

import uuid

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.base_repository import BaseRepository
from app.modules.documents.models import Document, DocumentChunk, DocumentVersion, ProcessingJob


class DocumentRepository(BaseRepository[Document]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Document)

    async def get_active_by_id(self, document_id: uuid.UUID) -> Document | None:
        stmt = select(Document).where(Document.id == document_id, Document.deleted_at.is_(None))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_hash(self, sha256_hash: str) -> Document | None:
        stmt = select(Document).where(
            Document.sha256_hash == sha256_hash, Document.deleted_at.is_(None)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_active(
        self, *, uploaded_by: uuid.UUID | None = None, offset: int = 0, limit: int = 20
    ) -> list[Document]:
        stmt = select(Document).where(Document.deleted_at.is_(None))
        if uploaded_by is not None:
            stmt = stmt.where(Document.uploaded_by == uploaded_by)
        stmt = stmt.order_by(Document.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_active(self, *, uploaded_by: uuid.UUID | None = None) -> int:
        stmt = select(func.count()).select_from(Document).where(Document.deleted_at.is_(None))
        if uploaded_by is not None:
            stmt = stmt.where(Document.uploaded_by == uploaded_by)
        result = await self.session.execute(stmt)
        return int(result.scalar_one())


class DocumentVersionRepository(BaseRepository[DocumentVersion]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, DocumentVersion)

    async def get_latest_version_number(self, document_id: uuid.UUID) -> int:
        stmt = select(func.max(DocumentVersion.version_number)).where(
            DocumentVersion.document_id == document_id
        )
        result = await self.session.execute(stmt)
        return result.scalar_one() or 0


class ProcessingJobRepository(BaseRepository[ProcessingJob]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, ProcessingJob)

    async def list_for_document(self, document_id: uuid.UUID) -> list[ProcessingJob]:
        stmt = (
            select(ProcessingJob)
            .where(ProcessingJob.document_id == document_id)
            .order_by(ProcessingJob.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class DocumentChunkRepository(BaseRepository[DocumentChunk]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, DocumentChunk)

    async def delete_for_document(self, document_id: uuid.UUID) -> None:
        """Used before re-persisting chunks so a job re-run (retry or
        explicit reprocess) replaces rather than duplicates them."""
        await self.session.execute(
            sa_delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
        )
        await self.session.flush()

    async def bulk_create(self, chunks: list[DocumentChunk]) -> None:
        self.session.add_all(chunks)
        await self.session.flush()

    async def count_for_document(self, document_id: uuid.UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
        )
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    async def list_for_document(self, document_id: uuid.UUID) -> list[DocumentChunk]:
        """Every chunk for a document, in order - added for Phase 3.2's
        extraction pipeline, which needs the full ordered set (unlike
        BaseRepository.list()'s default limit=20). Phase 2 never needed
        this: it only ever wrote chunks, never read them back."""
        stmt = (
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
            .order_by(DocumentChunk.chunk_index.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_ids(self, chunk_ids: list[uuid.UUID]) -> dict[uuid.UUID, DocumentChunk]:
        """chunk_id -> DocumentChunk, for a batch of chunks - Phase 4's
        graph builder groups entities by source_chunk and needs each
        chunk's full text to slice a connector string between two
        co-occurring entities, without an N+1 query per chunk."""
        if not chunk_ids:
            return {}
        stmt = select(DocumentChunk).where(DocumentChunk.id.in_(chunk_ids))
        result = await self.session.execute(stmt)
        return {chunk.id: chunk for chunk in result.scalars().all()}
