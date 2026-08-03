"""Application service for document upload, listing, retrieval, deletion,
and reprocessing.

AuditService is injected and called directly, the same documented exception
to "modules only read each other's repositories" already established in
app/modules/auth/service.py.
"""

import hashlib
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from app.common.base_service import BaseService
from app.core.exceptions import (
    ConflictError,
    NotFoundError,
    QuotaExceededError,
    UnprocessableUploadError,
)
from app.core.metrics import documents_processed_total, upload_duration_seconds
from app.modules.audit.service import AuditService
from app.modules.documents.domain import (
    QuotaExceededDomainError,
    UploadCandidate,
    UploadRejectedError,
    UploadValidator,
    check_duplicate,
    check_quota,
    generate_storage_filename,
    sanitize_display_filename,
)
from app.modules.documents.models import (
    Document,
    DocumentVersion,
    JobStatus,
    JobType,
    ProcessingJob,
    ProcessingStatus,
    StorageProviderKind,
)
from app.modules.documents.queue import JobQueue
from app.modules.documents.repository import (
    DocumentRepository,
    DocumentVersionRepository,
    ProcessingJobRepository,
)
from app.modules.documents.security.virus_scan import VirusScanner
from app.modules.documents.storage.base import StorageError, StorageProvider

_ACTIVE_PROCESSING_STATUSES = frozenset(
    {
        ProcessingStatus.QUEUED,
        ProcessingStatus.PROCESSING,
        ProcessingStatus.OCR,
        ProcessingStatus.EXTRACTING,
        ProcessingStatus.CHUNKING,
    }
)


async def _guarded_stream(
    source: AsyncIterator[bytes], *, max_bytes: int, hasher: "hashlib._Hash"
) -> AsyncIterator[bytes]:
    """Wraps an upload stream to enforce the size cap during streaming
    (not after) and feed the running hash in the same pass, so validation
    never requires a second read of the body."""
    total = 0
    async for chunk in source:
        total += len(chunk)
        if total > max_bytes:
            raise UploadRejectedError(f"File exceeds maximum size of {max_bytes} bytes")
        hasher.update(chunk)
        yield chunk


class DocumentService(BaseService):
    def __init__(
        self,
        *,
        document_repo: DocumentRepository,
        version_repo: DocumentVersionRepository,
        job_repo: ProcessingJobRepository,
        audit_service: AuditService,
        storage: StorageProvider,
        storage_provider_kind: StorageProviderKind,
        job_queue: JobQueue,
        upload_validator: UploadValidator,
        virus_scanner: VirusScanner,
        max_documents_per_user: int | None,
        signed_url_expire_seconds: int,
        processing_max_retries: int,
    ) -> None:
        super().__init__()
        self.document_repo = document_repo
        self.version_repo = version_repo
        self.job_repo = job_repo
        self.audit_service = audit_service
        self.storage = storage
        self.storage_provider_kind = storage_provider_kind
        self.job_queue = job_queue
        self.upload_validator = upload_validator
        self.virus_scanner = virus_scanner
        self.max_documents_per_user = max_documents_per_user
        self.signed_url_expire_seconds = signed_url_expire_seconds
        self.processing_max_retries = processing_max_retries

    async def upload(
        self,
        *,
        uploaded_by: uuid.UUID,
        original_filename: str,
        mime_type: str,
        stream: AsyncIterator[bytes],
    ) -> tuple[Document, ProcessingJob]:
        with upload_duration_seconds.time():
            return await self._upload(
                uploaded_by=uploaded_by,
                original_filename=original_filename,
                mime_type=mime_type,
                stream=stream,
            )

    async def _upload(
        self,
        *,
        uploaded_by: uuid.UUID,
        original_filename: str,
        mime_type: str,
        stream: AsyncIterator[bytes],
    ) -> tuple[Document, ProcessingJob]:
        candidate = UploadCandidate(original_filename=original_filename, mime_type=mime_type)
        try:
            extension = self.upload_validator.validate_filename_and_mime(candidate)
        except UploadRejectedError as exc:
            raise UnprocessableUploadError(str(exc)) from exc

        current_count = await self.document_repo.count_active(uploaded_by=uploaded_by)
        try:
            check_quota(current_count=current_count, max_documents=self.max_documents_per_user)
        except QuotaExceededDomainError as exc:
            raise QuotaExceededError(str(exc)) from exc

        storage_key = generate_storage_filename(extension)
        hasher = hashlib.sha256()
        guarded = _guarded_stream(
            stream, max_bytes=self.upload_validator.max_file_size_bytes, hasher=hasher
        )

        try:
            file_size = await self.storage.stream_upload(
                storage_key, guarded, content_type=mime_type
            )
        except (UploadRejectedError, StorageError) as exc:
            await self._cleanup_partial_upload(storage_key)
            if isinstance(exc, UploadRejectedError):
                raise UnprocessableUploadError(str(exc)) from exc
            raise UnprocessableUploadError("Upload failed while writing to storage") from exc

        try:
            self.upload_validator.validate_size(file_size)
        except UploadRejectedError as exc:
            await self._cleanup_partial_upload(storage_key)
            raise UnprocessableUploadError(str(exc)) from exc

        sha256_hash = hasher.hexdigest()

        existing = await self.document_repo.get_by_hash(sha256_hash)
        if check_duplicate(sha256_hash, existing.sha256_hash if existing else None):
            await self._cleanup_partial_upload(storage_key)
            assert existing is not None  # narrowed by check_duplicate
            raise ConflictError(
                "An identical document has already been uploaded",
                details={"existing_document_id": str(existing.id)},
            )

        scan_result = await self.virus_scanner.scan_stream(
            self.storage.stream_download(storage_key)
        )
        if not scan_result.is_clean:
            await self._cleanup_partial_upload(storage_key)
            raise UnprocessableUploadError(
                f"Upload rejected: {scan_result.threat_name or 'malware detected'}"
            )

        document = Document(
            uploaded_by=uploaded_by,
            filename=storage_key,
            original_filename=sanitize_display_filename(original_filename),
            extension=extension,
            mime_type=mime_type,
            file_size=file_size,
            sha256_hash=sha256_hash,
            storage_provider=self.storage_provider_kind,
            storage_key=storage_key,
            processing_status=ProcessingStatus.QUEUED,
        )
        created_document = await self.document_repo.create(document)

        await self.version_repo.create(
            DocumentVersion(
                document_id=created_document.id,
                version_number=1,
                uploaded_by=uploaded_by,
                storage_key=storage_key,
                sha256_hash=sha256_hash,
                file_size=file_size,
                uploaded_at=datetime.now(UTC),
            )
        )

        job = await self.job_repo.create(
            ProcessingJob(
                document_id=created_document.id,
                job_type=JobType.INGESTION,
                status=JobStatus.QUEUED,
                current_stage=ProcessingStatus.QUEUED,
                max_retries=self.processing_max_retries,
            )
        )

        await self.audit_service.record(
            user_id=uploaded_by,
            action="document.uploaded",
            resource_type="document",
            resource_id=created_document.id,
        )
        await self.job_queue.enqueue_job("process_document", str(created_document.id), str(job.id))

        self.logger.info(
            "document_uploaded", document_id=str(created_document.id), file_size=file_size
        )
        return created_document, job

    async def _cleanup_partial_upload(self, storage_key: str) -> None:
        try:
            await self.storage.delete(storage_key)
        except StorageError:
            self.logger.warning("cleanup_partial_upload_failed", storage_key=storage_key)

    async def list_documents(
        self, *, uploaded_by: uuid.UUID | None, offset: int, limit: int
    ) -> tuple[list[Document], int]:
        documents = await self.document_repo.list_active(
            uploaded_by=uploaded_by, offset=offset, limit=limit
        )
        total = await self.document_repo.count_active(uploaded_by=uploaded_by)
        return documents, total

    async def get_document(self, document_id: uuid.UUID) -> Document:
        document = await self.document_repo.get_active_by_id(document_id)
        if document is None:
            raise NotFoundError(f"Document {document_id} not found")
        return document

    async def get_download_url(self, document: Document) -> str:
        return await self.storage.signed_url(
            document.storage_key, expires_in=self.signed_url_expire_seconds
        )

    async def delete_document(self, document_id: uuid.UUID, *, deleted_by: uuid.UUID) -> None:
        document = await self.get_document(document_id)
        document.deleted_at = datetime.now(UTC)
        await self.document_repo.session.flush()
        await self.audit_service.record(
            user_id=deleted_by,
            action="document.deleted",
            resource_type="document",
            resource_id=document.id,
        )
        self.logger.info("document_deleted", document_id=str(document.id))

    async def reprocess_document(
        self, document_id: uuid.UUID, *, requested_by: uuid.UUID
    ) -> ProcessingJob:
        document = await self.get_document(document_id)
        if document.processing_status in _ACTIVE_PROCESSING_STATUSES:
            raise ConflictError(
                f"Document is already {document.processing_status.value}; "
                "wait for it to finish before reprocessing"
            )

        document.processing_status = ProcessingStatus.QUEUED
        document.processing_progress = 0
        await self.document_repo.session.flush()

        job = await self.job_repo.create(
            ProcessingJob(
                document_id=document.id,
                job_type=JobType.REPROCESS,
                status=JobStatus.QUEUED,
                current_stage=ProcessingStatus.QUEUED,
                max_retries=self.processing_max_retries,
            )
        )
        await self.audit_service.record(
            user_id=requested_by,
            action="document.reprocess_requested",
            resource_type="document",
            resource_id=document.id,
        )
        await self.job_queue.enqueue_job("process_document", str(document.id), str(job.id))
        documents_processed_total.labels(status="requeued").inc()
        return job

    async def get_job(self, job_id: uuid.UUID) -> ProcessingJob:
        job = await self.job_repo.get_by_id(job_id)
        if job is None:
            raise NotFoundError(f"Processing job {job_id} not found")
        return job
