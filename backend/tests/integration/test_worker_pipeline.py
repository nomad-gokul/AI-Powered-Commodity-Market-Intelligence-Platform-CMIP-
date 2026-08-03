"""End-to-end tests of the document ingestion pipeline (app/worker/tasks.py),
called directly rather than through a live ARQ worker process - this
exercises the exact same code a real worker runs (real Postgres, real
local storage via the test's isolated tmp_path, real Tesseract OCR), while
staying fast and deterministic.

process_document uses AsyncSessionLocal directly (it has to - a real
worker process has no HTTP request to hang a session override off), so it
does NOT participate in db_session's transaction-rollback isolation like
the API integration tests do. Every test that creates rows here cleans
them up explicitly in a finally block instead.
"""

import io
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import fitz
import pytest
from arq.worker import Retry
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.modules.auth.models import User
from app.modules.documents.models import (
    Document,
    DocumentChunk,
    JobStatus,
    JobType,
    ProcessingJob,
    ProcessingStatus,
    StorageProviderKind,
)
from app.modules.documents.storage.base import StorageError
from app.modules.documents.storage.factory import get_storage_provider
from app.worker.context import build_worker_context
from app.worker.tasks import process_document

pytestmark = pytest.mark.asyncio


def _native_text_pdf(paragraph: str) -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 100), paragraph)
    buffer = io.BytesIO()
    document.save(buffer)
    document.close()
    return buffer.getvalue()


def _blank_pdf() -> bytes:
    document = fitz.open()
    document.new_page()
    buffer = io.BytesIO()
    document.save(buffer)
    document.close()
    return buffer.getvalue()


def _scanned_text_image(text: str) -> bytes:
    image = Image.new("RGB", (900, 200), color="white")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("arial.ttf", 40)
    except OSError:
        font = ImageFont.load_default()
    draw.text((30, 70), text, fill="black", font=font)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class _Fixture:
    def __init__(self, user_id: uuid.UUID, document_id: uuid.UUID, job_id: uuid.UUID) -> None:
        self.user_id = user_id
        self.document_id = document_id
        self.job_id = job_id


@asynccontextmanager
async def _create_document_and_job(
    *, file_bytes: bytes, extension: str, mime_type: str, max_retries: int = 3
) -> AsyncIterator[_Fixture]:
    storage = get_storage_provider()
    storage_key = f"{uuid.uuid4().hex}{extension}"
    await storage.upload(storage_key, file_bytes, content_type=mime_type)

    async with AsyncSessionLocal() as session:
        user = User(
            email=f"worker-test-{uuid.uuid4().hex}@example.com",
            hashed_password="not-a-real-hash",
            full_name="Worker Test User",
            is_active=True,
        )
        session.add(user)
        await session.flush()

        document = Document(
            uploaded_by=user.id,
            filename=storage_key,
            original_filename="report.pdf",
            extension=extension,
            mime_type=mime_type,
            file_size=len(file_bytes),
            sha256_hash=uuid.uuid4().hex + uuid.uuid4().hex,
            storage_provider=StorageProviderKind.LOCAL,
            storage_key=storage_key,
            processing_status=ProcessingStatus.QUEUED,
        )
        session.add(document)
        await session.flush()

        job = ProcessingJob(
            document_id=document.id,
            job_type=JobType.INGESTION,
            status=JobStatus.QUEUED,
            current_stage=ProcessingStatus.QUEUED,
            max_retries=max_retries,
        )
        session.add(job)
        await session.commit()

        fixture = _Fixture(user.id, document.id, job.id)

    try:
        yield fixture
    finally:
        async with AsyncSessionLocal() as session:
            db_user = await session.get(User, fixture.user_id)
            if db_user is not None:
                await session.delete(db_user)  # cascades to documents/jobs/chunks/versions
            await session.commit()
        try:
            await storage.delete(storage_key)
        except StorageError:
            pass


async def _fetch_document(document_id: uuid.UUID) -> Document:
    async with AsyncSessionLocal() as session:
        document = await session.get(Document, document_id)
        assert document is not None
        return document


async def _fetch_job(job_id: uuid.UUID) -> ProcessingJob:
    async with AsyncSessionLocal() as session:
        job = await session.get(ProcessingJob, job_id)
        assert job is not None
        return job


async def _fetch_chunks(document_id: uuid.UUID) -> list[DocumentChunk]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
            .order_by(DocumentChunk.chunk_index)
        )
        return list(result.scalars().all())


@pytest.fixture
def worker_ctx(_isolated_document_storage: None) -> dict[str, object]:
    # Depends on _isolated_document_storage (autouse, from conftest.py) to
    # guarantee it runs first: build_worker_context() calls
    # get_storage_provider(), which is @lru_cache'd, so without this
    # explicit ordering the worker could pick up a stale provider rooted
    # at the real STORAGE_LOCAL_ROOT instead of the test's tmp_path.
    ctx = build_worker_context()
    ctx["job_id"] = "test-worker"
    return ctx


class TestNativeTextPipeline:
    async def test_processes_native_pdf_end_to_end(self, worker_ctx: dict[str, object]) -> None:
        paragraph = (
            "Dated Brent crude assessed at 82.14 dollars per barrel, up 0.35 on "
            "the day amid tightening North Sea supply. " * 3
        )
        async with _create_document_and_job(
            file_bytes=_native_text_pdf(paragraph), extension=".pdf", mime_type="application/pdf"
        ) as fixture:
            await process_document(worker_ctx, str(fixture.document_id), str(fixture.job_id))

            document = await _fetch_document(fixture.document_id)
            job = await _fetch_job(fixture.job_id)
            chunks = await _fetch_chunks(fixture.document_id)

            assert job.status == JobStatus.COMPLETED
            assert job.progress == 100
            assert job.completed_at is not None
            assert document.processing_status == ProcessingStatus.COMPLETED
            assert document.processing_progress == 100
            assert document.page_count == 1
            assert len(chunks) >= 1
            assert "Dated Brent" in chunks[0].text
            assert chunks[0].token_count > 0


class TestOCRFallbackPipeline:
    async def test_processes_blank_pdf_via_real_tesseract_ocr(
        self, worker_ctx: dict[str, object]
    ) -> None:
        if get_settings().ocr_tesseract_cmd is None:
            pytest.skip("OCR_TESSERACT_CMD not configured")

        async with _create_document_and_job(
            file_bytes=_blank_pdf(), extension=".pdf", mime_type="application/pdf"
        ) as fixture:
            await process_document(worker_ctx, str(fixture.document_id), str(fixture.job_id))

            job = await _fetch_job(fixture.job_id)
            document = await _fetch_document(fixture.document_id)
            assert job.status == JobStatus.COMPLETED
            assert document.processing_status == ProcessingStatus.COMPLETED

    async def test_processes_standalone_scanned_image_via_real_tesseract_ocr(
        self, worker_ctx: dict[str, object]
    ) -> None:
        if get_settings().ocr_tesseract_cmd is None:
            pytest.skip("OCR_TESSERACT_CMD not configured")

        async with _create_document_and_job(
            file_bytes=_scanned_text_image("BRENT CRUDE"), extension=".png", mime_type="image/png"
        ) as fixture:
            await process_document(worker_ctx, str(fixture.document_id), str(fixture.job_id))

            job = await _fetch_job(fixture.job_id)
            chunks = await _fetch_chunks(fixture.document_id)
            assert job.status == JobStatus.COMPLETED
            assert len(chunks) == 1
            assert "BRENT" in chunks[0].text.upper()


class TestIdempotentReprocessing:
    async def test_rerunning_the_pipeline_replaces_rather_than_duplicates_chunks(
        self, worker_ctx: dict[str, object]
    ) -> None:
        paragraph = "Freight rates for VLCCs on the Middle East Gulf to Asia route rose 4 points."
        async with _create_document_and_job(
            file_bytes=_native_text_pdf(paragraph), extension=".pdf", mime_type="application/pdf"
        ) as fixture:
            await process_document(worker_ctx, str(fixture.document_id), str(fixture.job_id))
            first_chunks = await _fetch_chunks(fixture.document_id)
            assert len(first_chunks) >= 1

            # Re-run the exact same job (as a retry or a reprocess would) -
            # chunk count must stay the same, not double.
            await process_document(worker_ctx, str(fixture.document_id), str(fixture.job_id))
            second_chunks = await _fetch_chunks(fixture.document_id)

            assert len(second_chunks) == len(first_chunks)
            assert [c.text for c in second_chunks] == [c.text for c in first_chunks]


class TestRetryAndDeadLetter:
    async def test_permanent_failure_retries_then_dead_letters(
        self, worker_ctx: dict[str, object]
    ) -> None:
        async with _create_document_and_job(
            file_bytes=_native_text_pdf("irrelevant"),
            extension=".pdf",
            mime_type="application/pdf",
            max_retries=2,
        ) as fixture:
            # Corrupt the storage key after upload so every attempt fails
            # at the "read file" stage - a deterministic, permanent failure.
            async with AsyncSessionLocal() as session:
                db_document = await session.get(Document, fixture.document_id)
                assert db_document is not None
                db_document.storage_key = "does-not-exist.pdf"
                await session.commit()

            # Simulates what ARQ's own scheduler would do on Retry: call
            # process_document again. Bounded at 10 attempts as a safety
            # net against an infinite-retry bug; max_retries=2 means this
            # should converge to a dead-lettered FAILED job in exactly 2.
            attempts = 0
            while attempts < 10:
                attempts += 1
                try:
                    await process_document(
                        worker_ctx, str(fixture.document_id), str(fixture.job_id)
                    )
                except Retry:
                    continue
                else:
                    break
            else:
                pytest.fail("retry loop did not converge within 10 attempts")

            job = await _fetch_job(fixture.job_id)
            final_document = await _fetch_document(fixture.document_id)
            assert job.status == JobStatus.FAILED
            assert job.retries == 2
            assert job.error_message is not None
            assert final_document.processing_status == ProcessingStatus.FAILED
