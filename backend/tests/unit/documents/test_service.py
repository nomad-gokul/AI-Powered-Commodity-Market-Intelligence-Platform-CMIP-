"""Unit tests for DocumentService, with repositories/AuditService/job queue
mocked and storage backed by an in-memory fake (so hashing/size-guarding
during streaming is exercised for real, the same reason Phase 1's
RateLimiter tests use a FakeRedis instead of an AsyncMock)."""

import hashlib
import uuid
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock

import pytest

from app.core.exceptions import (
    ConflictError,
    NotFoundError,
    QuotaExceededError,
    UnprocessableUploadError,
)
from app.modules.documents.domain import UploadValidator
from app.modules.documents.models import (
    Document,
    JobStatus,
    JobType,
    ProcessingStatus,
    StorageProviderKind,
)
from app.modules.documents.security.virus_scan import NullVirusScanner, ScanResult, VirusScanner
from app.modules.documents.service import DocumentService
from app.modules.documents.storage.base import StorageError, StorageProvider


class FakeStorage(StorageProvider):
    """An in-memory StorageProvider double - real enough to actually drive
    the streaming/hashing logic in DocumentService, unlike a plain
    AsyncMock (which would never iterate the generator it's handed)."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.deleted_keys: list[str] = []

    async def upload(self, key: str, data: bytes, *, content_type: str) -> None:
        self.objects[key] = data

    async def stream_upload(
        self, key: str, stream: AsyncIterator[bytes], *, content_type: str
    ) -> int:
        chunks = bytearray()
        async for chunk in stream:
            chunks.extend(chunk)
        self.objects[key] = bytes(chunks)
        return len(chunks)

    async def download(self, key: str) -> bytes:
        if key not in self.objects:
            raise StorageError(f"missing: {key}")
        return self.objects[key]

    async def stream_download(self, key: str, *, chunk_size: int = 1024) -> AsyncIterator[bytes]:
        if key not in self.objects:
            raise StorageError(f"missing: {key}")
        data = self.objects[key]
        for i in range(0, len(data), chunk_size):
            yield data[i : i + chunk_size]

    async def delete(self, key: str) -> None:
        self.objects.pop(key, None)
        self.deleted_keys.append(key)

    async def exists(self, key: str) -> bool:
        return key in self.objects

    async def signed_url(self, key: str, *, expires_in: int) -> str:
        return f"https://example.test/{key}?expires_in={expires_in}"


class DirtyVirusScanner(VirusScanner):
    async def scan_stream(self, stream: AsyncIterator[bytes]) -> ScanResult:
        return ScanResult(is_clean=False, threat_name="EICAR-Test-Signature")


async def _stream(data: bytes, chunk_size: int = 1024) -> AsyncIterator[bytes]:
    for i in range(0, len(data), chunk_size):
        yield data[i : i + chunk_size]


def make_document(**overrides: object) -> Document:
    defaults: dict[str, object] = dict(
        id=uuid.uuid4(),
        uploaded_by=uuid.uuid4(),
        filename="abc123.pdf",
        original_filename="report.pdf",
        extension=".pdf",
        mime_type="application/pdf",
        file_size=10,
        sha256_hash="a" * 64,
        storage_provider=StorageProviderKind.LOCAL,
        storage_key="abc123.pdf",
        processing_status=ProcessingStatus.UPLOADED,
        deleted_at=None,
    )
    defaults.update(overrides)
    return Document(**defaults)  # type: ignore[arg-type]


@pytest.fixture
def env() -> tuple[DocumentService, dict[str, AsyncMock], FakeStorage]:
    document_repo = AsyncMock()
    version_repo = AsyncMock()
    job_repo = AsyncMock()
    audit_service = AsyncMock()
    job_queue = AsyncMock()
    storage = FakeStorage()

    document_repo.create.side_effect = lambda d: d
    version_repo.create.side_effect = lambda v: v
    job_repo.create.side_effect = lambda j: j

    service = DocumentService(
        document_repo=document_repo,
        version_repo=version_repo,
        job_repo=job_repo,
        audit_service=audit_service,
        storage=storage,
        storage_provider_kind=StorageProviderKind.LOCAL,
        job_queue=job_queue,
        upload_validator=UploadValidator(
            allowed_extensions=[".pdf"], max_file_size_bytes=1024 * 1024
        ),
        virus_scanner=NullVirusScanner(),
        max_documents_per_user=None,
        signed_url_expire_seconds=3600,
        processing_max_retries=3,
    )
    repos = {
        "document_repo": document_repo,
        "version_repo": version_repo,
        "job_repo": job_repo,
        "audit_service": audit_service,
        "job_queue": job_queue,
    }
    return service, repos, storage


class TestUpload:
    async def test_successful_upload_creates_document_version_and_job(
        self, env: tuple[DocumentService, dict[str, AsyncMock], FakeStorage]
    ) -> None:
        service, repos, storage = env
        repos["document_repo"].count_active.return_value = 0
        repos["document_repo"].get_by_hash.return_value = None
        uploader_id = uuid.uuid4()

        document, job = await service.upload(
            uploaded_by=uploader_id,
            original_filename="report.pdf",
            mime_type="application/pdf",
            stream=_stream(b"%PDF-1.4 fake pdf content"),
        )

        assert document.original_filename == "report.pdf"
        assert document.uploaded_by == uploader_id
        assert document.processing_status == ProcessingStatus.QUEUED
        assert document.file_size == len(b"%PDF-1.4 fake pdf content")
        assert job.job_type == JobType.INGESTION
        assert job.status == JobStatus.QUEUED
        repos["version_repo"].create.assert_awaited_once()
        repos["audit_service"].record.assert_awaited_once()
        repos["job_queue"].enqueue_job.assert_awaited_once_with(
            "process_document", str(document.id), str(job.id)
        )
        assert document.storage_key in storage.objects

    async def test_rejects_disallowed_extension(
        self, env: tuple[DocumentService, dict[str, AsyncMock], FakeStorage]
    ) -> None:
        service, repos, _ = env
        repos["document_repo"].count_active.return_value = 0

        with pytest.raises(UnprocessableUploadError):
            await service.upload(
                uploaded_by=uuid.uuid4(),
                original_filename="malware.exe",
                mime_type="application/pdf",
                stream=_stream(b"data"),
            )
        repos["job_queue"].enqueue_job.assert_not_awaited()

    async def test_rejects_when_quota_exceeded(
        self, env: tuple[DocumentService, dict[str, AsyncMock], FakeStorage]
    ) -> None:
        service, repos, _ = env
        service.max_documents_per_user = 5
        repos["document_repo"].count_active.return_value = 5

        with pytest.raises(QuotaExceededError):
            await service.upload(
                uploaded_by=uuid.uuid4(),
                original_filename="report.pdf",
                mime_type="application/pdf",
                stream=_stream(b"data"),
            )

    async def test_rejects_duplicate_and_cleans_up_storage(
        self, env: tuple[DocumentService, dict[str, AsyncMock], FakeStorage]
    ) -> None:
        service, repos, storage = env
        repos["document_repo"].count_active.return_value = 0
        actual_hash = hashlib.sha256(b"data").hexdigest()
        existing = make_document(sha256_hash=actual_hash)
        repos["document_repo"].get_by_hash.return_value = existing

        with pytest.raises(ConflictError) as exc_info:
            await service.upload(
                uploaded_by=uuid.uuid4(),
                original_filename="report.pdf",
                mime_type="application/pdf",
                stream=_stream(b"data"),
            )
        assert exc_info.value.details["existing_document_id"] == str(existing.id)
        assert storage.objects == {}  # the partial upload was deleted
        repos["job_queue"].enqueue_job.assert_not_awaited()

    async def test_rejects_infected_upload_and_cleans_up_storage(
        self, env: tuple[DocumentService, dict[str, AsyncMock], FakeStorage]
    ) -> None:
        service, repos, storage = env
        repos["document_repo"].count_active.return_value = 0
        repos["document_repo"].get_by_hash.return_value = None
        service.virus_scanner = DirtyVirusScanner()

        with pytest.raises(UnprocessableUploadError, match="EICAR"):
            await service.upload(
                uploaded_by=uuid.uuid4(),
                original_filename="report.pdf",
                mime_type="application/pdf",
                stream=_stream(b"data"),
            )
        assert storage.objects == {}
        repos["job_queue"].enqueue_job.assert_not_awaited()

    async def test_rejects_oversized_stream_and_cleans_up_storage(
        self, env: tuple[DocumentService, dict[str, AsyncMock], FakeStorage]
    ) -> None:
        service, repos, storage = env
        service.upload_validator = UploadValidator(
            allowed_extensions=[".pdf"], max_file_size_bytes=10
        )
        repos["document_repo"].count_active.return_value = 0

        with pytest.raises(UnprocessableUploadError, match="exceeds"):
            await service.upload(
                uploaded_by=uuid.uuid4(),
                original_filename="report.pdf",
                mime_type="application/pdf",
                stream=_stream(b"this is way more than ten bytes"),
            )
        assert storage.objects == {}


class TestListAndGet:
    async def test_list_documents_delegates_to_repo(
        self, env: tuple[DocumentService, dict[str, AsyncMock], FakeStorage]
    ) -> None:
        service, repos, _ = env
        expected = [make_document()]
        repos["document_repo"].list_active.return_value = expected
        repos["document_repo"].count_active.return_value = 1

        documents, total = await service.list_documents(uploaded_by=None, offset=0, limit=20)

        assert documents == expected
        assert total == 1

    async def test_get_document_raises_not_found(
        self, env: tuple[DocumentService, dict[str, AsyncMock], FakeStorage]
    ) -> None:
        service, repos, _ = env
        repos["document_repo"].get_active_by_id.return_value = None

        with pytest.raises(NotFoundError):
            await service.get_document(uuid.uuid4())

    async def test_get_download_url_calls_storage(
        self, env: tuple[DocumentService, dict[str, AsyncMock], FakeStorage]
    ) -> None:
        service, _, _ = env
        document = make_document()
        url = await service.get_download_url(document)
        assert document.storage_key in url


class TestDelete:
    async def test_delete_sets_deleted_at_and_records_audit(
        self, env: tuple[DocumentService, dict[str, AsyncMock], FakeStorage]
    ) -> None:
        service, repos, _ = env
        document = make_document()
        repos["document_repo"].get_active_by_id.return_value = document
        repos["document_repo"].session = AsyncMock()

        await service.delete_document(document.id, deleted_by=uuid.uuid4())

        assert document.deleted_at is not None
        repos["audit_service"].record.assert_awaited_once()


class TestReprocess:
    async def test_reprocess_requeues_and_enqueues_job(
        self, env: tuple[DocumentService, dict[str, AsyncMock], FakeStorage]
    ) -> None:
        service, repos, _ = env
        document = make_document(processing_status=ProcessingStatus.COMPLETED)
        repos["document_repo"].get_active_by_id.return_value = document
        repos["document_repo"].session = AsyncMock()

        job = await service.reprocess_document(document.id, requested_by=uuid.uuid4())

        assert document.processing_status == ProcessingStatus.QUEUED
        assert document.processing_progress == 0
        assert job.job_type == JobType.REPROCESS
        repos["job_queue"].enqueue_job.assert_awaited_once_with(
            "process_document", str(document.id), str(job.id)
        )

    async def test_reprocess_rejects_document_already_in_progress(
        self, env: tuple[DocumentService, dict[str, AsyncMock], FakeStorage]
    ) -> None:
        service, repos, _ = env
        document = make_document(processing_status=ProcessingStatus.EXTRACTING)
        repos["document_repo"].get_active_by_id.return_value = document

        with pytest.raises(ConflictError):
            await service.reprocess_document(document.id, requested_by=uuid.uuid4())
        repos["job_queue"].enqueue_job.assert_not_awaited()

    async def test_get_job_raises_not_found(
        self, env: tuple[DocumentService, dict[str, AsyncMock], FakeStorage]
    ) -> None:
        service, repos, _ = env
        repos["job_repo"].get_by_id.return_value = None

        with pytest.raises(NotFoundError):
            await service.get_job(uuid.uuid4())
