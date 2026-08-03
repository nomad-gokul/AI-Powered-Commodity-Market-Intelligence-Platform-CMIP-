"""ORM models for document ingestion: documents, version history, processing
jobs, and chunk metadata (no embeddings yet - those arrive with pgvector in
a later phase).

Documents/DocumentVersions/DocumentChunks have no business rules of their
own (rule-light persistence entities), so the ORM model doubles as the
domain object, same pattern as app/modules/auth/models.py. The real rules
(upload validation, duplicate detection, quota enforcement) live in
app/modules/documents/domain.py.
"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, TimestampMixin


class StorageProviderKind(StrEnum):
    LOCAL = "local"
    S3 = "s3"


class UploadStatus(StrEnum):
    PENDING = "pending"
    UPLOADED = "uploaded"
    FAILED = "failed"


class ProcessingStatus(StrEnum):
    """The document's current position in the ingestion pipeline.

    Distinct from ProcessingJob.status (the job-execution lifecycle): a
    document has one processing_status at a time, reflecting the furthest
    pipeline stage reached by its most recent job.
    """

    UPLOADED = "uploaded"
    QUEUED = "queued"
    PROCESSING = "processing"
    OCR = "ocr"
    EXTRACTING = "extracting"
    CHUNKING = "chunking"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobType(StrEnum):
    INGESTION = "ingestion"
    REPROCESS = "reprocess"


class JobStatus(StrEnum):
    """The job's own execution lifecycle - separate from the document's
    pipeline-stage ProcessingStatus above."""

    QUEUED = "queued"
    RUNNING = "running"
    RETRYING = "retrying"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# A native Postgres enum per Python StrEnum, named explicitly so Alembic
# autogenerate diffs stay stable (matches the NAMING_CONVENTION rationale
# in app/core/database.py).
def _values(enum_cls: type[StrEnum]) -> Any:
    return lambda e: [m.value for m in e]


_storage_provider_enum = Enum(
    StorageProviderKind,
    name="storage_provider_kind",
    values_callable=_values(StorageProviderKind),
)
_upload_status_enum = Enum(
    UploadStatus, name="upload_status", values_callable=_values(UploadStatus)
)
_processing_status_enum = Enum(
    ProcessingStatus, name="processing_status", values_callable=_values(ProcessingStatus)
)
_job_type_enum = Enum(JobType, name="job_type", values_callable=_values(JobType))
_job_status_enum = Enum(JobStatus, name="job_status", values_callable=_values(JobStatus))


class Document(TimestampMixin, Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # `filename` is the server-generated storage-safe name; `original_filename`
    # is the untrusted client-supplied name, kept for display only and never
    # used to build a filesystem/object-storage path (see domain.py).
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    extension: Mapped[str] = mapped_column(String(16), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    storage_provider: Mapped[StorageProviderKind] = mapped_column(
        _storage_provider_enum, nullable=False
    )
    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False)

    upload_status: Mapped[UploadStatus] = mapped_column(
        _upload_status_enum, nullable=False, default=UploadStatus.PENDING
    )
    processing_status: Mapped[ProcessingStatus] = mapped_column(
        _processing_status_enum, nullable=False, default=ProcessingStatus.UPLOADED
    )
    # Denormalized cache of the active job's progress, so GET /documents/{id}
    # doesn't need a join to processing_jobs just to render a progress bar.
    processing_progress: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)

    language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DocumentVersion(TimestampMixin, Base):
    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint("document_id", "version_number", name="uq_document_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Needed to actually retrieve this version's bytes - a version row with
    # no pointer to its own content would be unreadable, so these three
    # columns are added beyond the originally specified minimal set.
    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    sha256_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProcessingJob(TimestampMixin, Base):
    __tablename__ = "processing_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    job_type: Mapped[JobType] = mapped_column(_job_type_enum, nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        _job_status_enum, nullable=False, default=JobStatus.QUEUED
    )
    # Mirrors ProcessingStatus so a job row shows which pipeline stage it was
    # in when it last reported progress, without redefining a second enum.
    current_stage: Mapped[ProcessingStatus] = mapped_column(
        _processing_status_enum, nullable=False, default=ProcessingStatus.QUEUED
    )
    progress: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    retries: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    max_retries: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=3)
    worker_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    execution_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class DocumentChunk(TimestampMixin, Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_document_chunk_index"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
