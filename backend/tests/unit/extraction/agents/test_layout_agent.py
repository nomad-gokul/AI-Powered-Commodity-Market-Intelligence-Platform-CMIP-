"""Unit tests for LayoutAgent: real PyMuPDF geometry, one scripted LLM
call for the interpretive reading-order classification."""

import io

import fitz
from shared.agent_contracts import AgentContext
from shared.ai_contracts import LLMUsage

from app.modules.extraction.agents.layout_agent import LayoutAgent
from app.modules.extraction.agents.schemas import LayoutModel, PageLayout, ReadingOrderBlock
from app.modules.extraction.prompts import get_extraction_prompt_registry

from ._doubles import ScriptedStructuredOutputService


def _pdf_with_two_words() -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "Hello")
    page.insert_text((150, 72), "World")
    buffer = io.BytesIO()
    document.save(buffer)
    document.close()
    return buffer.getvalue()


def _context() -> AgentContext:
    return AgentContext(correlation_id="test-correlation")


def _layout_model() -> LayoutModel:
    return LayoutModel(
        pages=[
            PageLayout(
                page_number=1,
                is_multi_column=False,
                column_count=1,
                reading_order=[ReadingOrderBlock(block_index=0, role="body")],
            )
        ]
    )


class TestRun:
    async def test_returns_real_word_spans_and_llm_layout(self) -> None:
        usage = LLMUsage(prompt_tokens=50, completion_tokens=10, total_tokens=60)
        structured = ScriptedStructuredOutputService(responses=[(_layout_model(), usage)])
        agent = LayoutAgent(
            structured_output_service=structured,  # type: ignore[arg-type]
            prompt_registry=get_extraction_prompt_registry(),
            model="test-model",
            pdf_bytes=_pdf_with_two_words(),
        )

        result = await agent.run(_context())

        assert result.total_usage == usage
        assert result.layout.pages[0].page_number == 1
        span_texts = [s.text for s in result.spans]
        assert span_texts == ["Hello", "World"]

    async def test_summary_sent_to_llm_reflects_real_positions(self) -> None:
        structured = ScriptedStructuredOutputService(responses=[(_layout_model(), LLMUsage())])
        agent = LayoutAgent(
            structured_output_service=structured,  # type: ignore[arg-type]
            prompt_registry=get_extraction_prompt_registry(),
            model="test-model",
            pdf_bytes=_pdf_with_two_words(),
        )

        await agent.run(_context())

        request = structured.requests[0]
        assert "Hello" in (request.user_prompt or "")
        assert "bbox=" in (request.user_prompt or "")
        assert request.prompt_package_name == "layout_understanding"

    def test_name_is_stable(self) -> None:
        agent = LayoutAgent(
            structured_output_service=ScriptedStructuredOutputService([]),  # type: ignore[arg-type]
            prompt_registry=get_extraction_prompt_registry(),
            model="m",
            pdf_bytes=_pdf_with_two_words(),
        )
        assert agent.name == "layout"
