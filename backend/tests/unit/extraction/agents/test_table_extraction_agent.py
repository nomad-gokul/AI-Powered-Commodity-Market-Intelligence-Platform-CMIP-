"""Unit tests for TableExtractionAgent: reuses Phase 2's already-persisted
table row-grids for structure, a fresh pdfplumber pass for real cell
bounding boxes, one LLM call per table for semantic interpretation only."""

import io
import uuid

import fitz
from shared.agent_contracts import AgentContext
from shared.ai_contracts import LLMUsage

from app.modules.documents.models import DocumentChunk
from app.modules.extraction.agents.schemas import TableCellItem, TableExtractionOutput
from app.modules.extraction.agents.table_extraction_agent import TableExtractionAgent
from app.modules.extraction.prompts import get_extraction_prompt_registry

from ._doubles import ScriptedStructuredOutputService


def _pdf_with_2x2_table() -> bytes:
    document = fitz.open()
    page = document.new_page(width=300, height=200)
    x0, y0, x1, y1 = 50, 50, 250, 150
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


def _pdf_with_no_table() -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "no table here")
    buffer = io.BytesIO()
    document.save(buffer)
    document.close()
    return buffer.getvalue()


def _chunk_with_table(*, page_number: int = 1, index: int = 0) -> DocumentChunk:
    return DocumentChunk(
        id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        chunk_index=index,
        page_number=page_number,
        text="a chunk on the page with a table",
        token_count=8,
        metadata_json={"tables": [[["Grade", "Price"], ["Brent", "82.14"]]]},
    )


def _context() -> AgentContext:
    return AgentContext(correlation_id="test-correlation")


class TestRun:
    async def test_returns_grounded_table_with_real_structure_and_bboxes(self) -> None:
        chunk = _chunk_with_table()
        output = TableExtractionOutput(
            title="Grade/Price table",
            confidence=0.9,
            cells=[
                TableCellItem(row=0, column=0, normalized_value="Grade", confidence=0.9),
                TableCellItem(row=0, column=1, normalized_value="Price", confidence=0.9),
                TableCellItem(row=1, column=0, normalized_value="Brent", confidence=0.9),
                TableCellItem(row=1, column=1, normalized_value="82.14", confidence=0.9),
            ],
        )
        usage = LLMUsage(prompt_tokens=20, completion_tokens=10, total_tokens=30)
        structured = ScriptedStructuredOutputService(responses=[(output, usage)])
        agent = TableExtractionAgent(
            structured_output_service=structured,  # type: ignore[arg-type]
            prompt_registry=get_extraction_prompt_registry(),
            model="test-model",
            chunks=[chunk],
            pdf_bytes=_pdf_with_2x2_table(),
        )

        result = await agent.run(_context())

        assert len(result.tables) == 1
        table = result.tables[0]
        assert table.title == "Grade/Price table"
        assert table.row_count == 2
        assert table.column_count == 2
        assert table.bounding_box is not None
        assert len(table.cells) == 4
        brent_cell = next(c for c in table.cells if c.row == 1 and c.column == 0)
        assert brent_cell.raw_value == "Brent"
        assert brent_cell.normalized_value == "Brent"
        assert brent_cell.bounding_box is not None
        assert result.total_usage == usage

    async def test_no_tables_in_any_chunk_makes_no_llm_call(self) -> None:
        chunk = DocumentChunk(
            id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            chunk_index=0,
            page_number=1,
            text="just prose",
            token_count=2,
            metadata_json={},
        )
        structured = ScriptedStructuredOutputService(responses=[])
        agent = TableExtractionAgent(
            structured_output_service=structured,  # type: ignore[arg-type]
            prompt_registry=get_extraction_prompt_registry(),
            model="test-model",
            chunks=[chunk],
            pdf_bytes=_pdf_with_no_table(),
        )

        result = await agent.run(_context())

        assert result.tables == []
        assert structured.requests == []

    async def test_same_table_shared_across_chunks_on_same_page_is_processed_once(self) -> None:
        chunk_a = _chunk_with_table(page_number=1, index=0)
        chunk_b = _chunk_with_table(page_number=1, index=1)  # same page, same table metadata
        output = TableExtractionOutput(title=None, confidence=0.9, cells=[])
        structured = ScriptedStructuredOutputService(responses=[(output, LLMUsage())])
        agent = TableExtractionAgent(
            structured_output_service=structured,  # type: ignore[arg-type]
            prompt_registry=get_extraction_prompt_registry(),
            model="test-model",
            chunks=[chunk_a, chunk_b],
            pdf_bytes=_pdf_with_2x2_table(),
        )

        result = await agent.run(_context())

        assert len(structured.requests) == 1
        assert len(result.tables) == 1

    def test_name_is_stable(self) -> None:
        agent = TableExtractionAgent(
            structured_output_service=ScriptedStructuredOutputService([]),  # type: ignore[arg-type]
            prompt_registry=get_extraction_prompt_registry(),
            model="m",
            chunks=[],
            pdf_bytes=_pdf_with_no_table(),
        )
        assert agent.name == "table_extraction"
