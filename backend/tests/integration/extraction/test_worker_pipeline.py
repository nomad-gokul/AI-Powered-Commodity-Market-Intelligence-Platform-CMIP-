"""End-to-end test of the semantic extraction pipeline (app/worker/tasks.py's
run_extraction), called directly against real Postgres and real local
storage - the same pattern Phase 2's test_worker_pipeline.py established.

The LLM layer is the one thing stubbed: a scripted StructuredOutputService
double stands in for real Groq calls (no API key needed to run this
suite), but everything else is real - PyMuPDF/pdfplumber geometry
extraction, SequentialEngine execution, and Postgres persistence via the
real repositories.

run_extraction uses AsyncSessionLocal directly (a real worker process has
no HTTP request to hang a session override off), so it does NOT
participate in db_session's transaction-rollback isolation - rows created
here are cleaned up explicitly.
"""

import io
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import fitz
import pytest
from pydantic import BaseModel
from shared.ai_contracts import LLMRequest, LLMUsage
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.modules.auth.models import User
from app.modules.documents.models import Document, DocumentChunk, StorageProviderKind
from app.modules.documents.storage.factory import get_storage_provider
from app.modules.extraction.agents.schemas import (
    DocumentMetadataOutput,
    DocumentTypeEnum,
    EntityExtractionOutput,
    ExtractedEntityItem,
    LayoutModel,
    PageLayout,
    ReadingOrderBlock,
    TableExtractionOutput,
)
from app.modules.extraction.models import (
    EntityMention,
    EntityType,
    ExtractedEntity,
    ExtractedTable,
    ExtractionRun,
    ExtractionStatus,
    TableCell,
)
from app.modules.extraction.prompts import get_extraction_prompt_registry
from app.worker.tasks import run_extraction

pytestmark = pytest.mark.asyncio


class _ScriptedStructuredOutputService:
    def __init__(self, responses: list[tuple[BaseModel, LLMUsage]]) -> None:
        self._responses = list(responses)
        self.requests: list[LLMRequest] = []

    async def generate_structured_with_usage(
        self, request: LLMRequest, response_model: type[BaseModel], **kwargs: object
    ) -> tuple[BaseModel, LLMUsage]:
        self.requests.append(request)
        return self._responses.pop(0)


def _pdf_with_table(paragraph: str) -> bytes:
    document = fitz.open()
    page = document.new_page(width=400, height=300)
    page.insert_text((72, 72), paragraph)
    x0, y0, x1, y1 = 50, 150, 250, 250
    xm, ym = (x0 + x1) / 2, (y0 + y1) / 2
    page.draw_rect(fitz.Rect(x0, y0, x1, y1))
    page.draw_line((xm, y0), (xm, y1))
    page.draw_line((x0, ym), (x1, ym))
    page.insert_text((x0 + 10, ym - 10), "Grade")
    page.insert_text((xm + 10, ym - 10), "Price")
    page.insert_text((x0 + 10, y1 - 10), "Brent")
    page.insert_text((xm + 10, y1 - 10), "82.14")
    buffer = io.BytesIO()
    document.save(buffer)
    document.close()
    return buffer.getvalue()


class _Fixture:
    def __init__(self, document_id: uuid.UUID, extraction_run_id: uuid.UUID) -> None:
        self.document_id = document_id
        self.extraction_run_id = extraction_run_id


@asynccontextmanager
async def _create_document_chunk_and_run(*, pdf_bytes: bytes) -> AsyncIterator[_Fixture]:
    storage = get_storage_provider()
    storage_key = f"{uuid.uuid4().hex}.pdf"
    await storage.upload(storage_key, pdf_bytes, content_type="application/pdf")

    async with AsyncSessionLocal() as session:
        user = (await session.execute(select(User).limit(1))).scalars().first()
        document = Document(
            uploaded_by=user.id if user else None,
            filename=storage_key,
            original_filename="report.pdf",
            extension=".pdf",
            mime_type="application/pdf",
            file_size=len(pdf_bytes),
            sha256_hash="0" * 64,
            storage_provider=StorageProviderKind.LOCAL,
            storage_key=storage_key,
        )
        session.add(document)
        await session.flush()

        chunk = DocumentChunk(
            document_id=document.id,
            chunk_index=0,
            page_number=1,
            text="Brent crude rose to $82.14 per barrel today.",
            token_count=9,
            metadata_json={"tables": [[["Grade", "Price"], ["Brent", "82.14"]]]},
        )
        session.add(chunk)

        run = ExtractionRun(
            document_id=document.id,
            pipeline_version="3.2.0",
            provider="groq",
            model="test-model",
            prompt_version="1.0",
            prompt_hash="test-hash",
            status=ExtractionStatus.PENDING,
        )
        session.add(run)
        await session.commit()

        fixture = _Fixture(document_id=document.id, extraction_run_id=run.id)

    try:
        yield fixture
    finally:
        async with AsyncSessionLocal() as session:
            await session.execute(
                delete(TableCell).where(
                    TableCell.table_id.in_(
                        select(ExtractedTable.id).where(
                            ExtractedTable.extraction_run_id == fixture.extraction_run_id
                        )
                    )
                )
            )
            await session.execute(
                delete(EntityMention).where(
                    EntityMention.entity_id.in_(
                        select(ExtractedEntity.id).where(
                            ExtractedEntity.extraction_run_id == fixture.extraction_run_id
                        )
                    )
                )
            )
            await session.execute(
                delete(ExtractedEntity).where(
                    ExtractedEntity.extraction_run_id == fixture.extraction_run_id
                )
            )
            await session.execute(
                delete(ExtractedTable).where(
                    ExtractedTable.extraction_run_id == fixture.extraction_run_id
                )
            )
            await session.execute(
                delete(ExtractionRun).where(ExtractionRun.id == fixture.extraction_run_id)
            )
            await session.execute(
                delete(DocumentChunk).where(DocumentChunk.document_id == fixture.document_id)
            )
            await session.execute(delete(Document).where(Document.id == fixture.document_id))
            await session.commit()
        await storage.delete(storage_key)


def _scripted_responses() -> list[tuple[BaseModel, LLMUsage]]:
    document_understanding = DocumentMetadataOutput(
        document_type=DocumentTypeEnum.PRICE_REPORT,
        commodity="crude oil",
        business_domain="crude oil trading",
        extraction_strategy="focus on the price table",
        confidence=0.9,
    )
    layout = LayoutModel(
        pages=[
            PageLayout(
                page_number=1,
                is_multi_column=False,
                column_count=1,
                reading_order=[ReadingOrderBlock(block_index=0, role="body")],
            )
        ]
    )
    entities = EntityExtractionOutput(
        entities=[
            ExtractedEntityItem(
                entity_type=EntityType.COMMODITY,
                raw_value="Brent",
                normalized_value="Brent crude",
                confidence=0.95,
            )
        ]
    )
    table = TableExtractionOutput(
        title="Grade/Price",
        confidence=0.9,
        cells=[],
    )
    usage = LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    return [
        (document_understanding, usage),
        (layout, usage),
        (entities, usage),
        (table, usage),
    ]


class TestRunExtraction:
    async def test_full_pipeline_persists_real_entities_and_tables(self) -> None:
        async with _create_document_chunk_and_run(
            pdf_bytes=_pdf_with_table("Brent crude rose to $82.14 per barrel today.")
        ) as fixture:
            ctx = {
                "storage": get_storage_provider(),
                "structured_output_service": _ScriptedStructuredOutputService(
                    _scripted_responses()
                ),
                "prompt_registry": get_extraction_prompt_registry(),
            }

            await run_extraction(ctx, str(fixture.document_id), str(fixture.extraction_run_id))

            async with AsyncSessionLocal() as session:
                run = await session.get(ExtractionRun, fixture.extraction_run_id)
                assert run is not None
                assert run.status == ExtractionStatus.COMPLETED
                assert run.completed_at is not None
                assert run.processing_time_ms is not None
                assert run.token_usage["total_tokens"] == 60  # 4 steps x 15 tokens

                entities = (
                    (
                        await session.execute(
                            select(ExtractedEntity).where(
                                ExtractedEntity.extraction_run_id == fixture.extraction_run_id
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                assert len(entities) == 1
                assert entities[0].raw_value == "Brent"
                assert entities[0].bounding_box is not None  # grounded via real geometry

                tables = (
                    (
                        await session.execute(
                            select(ExtractedTable).where(
                                ExtractedTable.extraction_run_id == fixture.extraction_run_id
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                assert len(tables) == 1
                assert tables[0].row_count == 2
                assert tables[0].column_count == 2

    async def test_missing_document_row_is_a_no_op(self) -> None:
        ctx = {
            "storage": get_storage_provider(),
            "structured_output_service": _ScriptedStructuredOutputService([]),
            "prompt_registry": get_extraction_prompt_registry(),
        }
        # Neither document nor extraction run exist - should return quietly.
        await run_extraction(ctx, str(uuid.uuid4()), str(uuid.uuid4()))

    async def test_unconfigured_llm_provider_fails_the_run_clearly(self) -> None:
        """Regression test: build_worker_context() degrades to a None
        structured_output_service (logged warning, not a crash) when no
        LLM provider is configured - a real run_extraction job invoked in
        that state must fail with a clear, actionable error_message, not
        a bare AttributeError three layers down inside an agent. Caught
        live against the real docker-compose stack (this dev environment
        has no GROQ_API_KEY) before being fixed and covered here.
        """
        async with _create_document_chunk_and_run(
            pdf_bytes=_pdf_with_table("Brent crude rose to $82.14 per barrel today.")
        ) as fixture:
            ctx = {
                "storage": get_storage_provider(),
                "structured_output_service": None,
                "prompt_registry": get_extraction_prompt_registry(),
            }

            await run_extraction(ctx, str(fixture.document_id), str(fixture.extraction_run_id))

            async with AsyncSessionLocal() as session:
                run = await session.get(ExtractionRun, fixture.extraction_run_id)
                assert run is not None
                assert run.status == ExtractionStatus.FAILED
                assert run.error_message is not None
                assert "No LLM provider is configured" in run.error_message
                assert "AttributeError" not in run.error_message
