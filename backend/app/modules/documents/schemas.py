"""Request/response DTOs for the documents module."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.modules.documents.models import JobStatus, JobType, ProcessingStatus, UploadStatus


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    uploaded_by: uuid.UUID | None
    original_filename: str
    extension: str
    mime_type: str
    file_size: int
    sha256_hash: str
    upload_status: UploadStatus
    processing_status: ProcessingStatus
    processing_progress: int
    language: str | None
    page_count: int | None
    metadata_json: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class DocumentDetailRead(DocumentRead):
    download_url: str | None = None


class ProcessingJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_id: uuid.UUID
    job_type: JobType
    status: JobStatus
    current_stage: ProcessingStatus
    progress: int
    retries: int
    max_retries: int
    worker_id: str | None
    started_at: datetime | None
    completed_at: datetime | None
    failed_at: datetime | None
    execution_time_ms: int | None
    error_message: str | None
    created_at: datetime


class UploadResponse(BaseModel):
    document: DocumentRead
    job: ProcessingJobRead
