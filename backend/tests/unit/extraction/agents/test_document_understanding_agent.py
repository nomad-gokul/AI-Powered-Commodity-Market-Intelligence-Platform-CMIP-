"""Unit tests for DocumentUnderstandingAgent."""

import uuid

from shared.agent_contracts import AgentContext
from shared.ai_contracts import LLMUsage

from app.modules.documents.models import DocumentChunk
from app.modules.extraction.agents.document_understanding_agent import DocumentUnderstandingAgent
from app.modules.extraction.agents.schemas import DocumentMetadataOutput, DocumentTypeEnum
from app.modules.extraction.prompts import get_extraction_prompt_registry

from ._doubles import ScriptedStructuredOutputService


def _chunk(text: str, index: int = 0) -> DocumentChunk:
    return DocumentChunk(
        id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        chunk_index=index,
        page_number=1,
        text=text,
        token_count=len(text.split()),
        metadata_json={},
    )


def _context() -> AgentContext:
    return AgentContext(correlation_id="test-correlation")


class TestRun:
    async def test_returns_metadata_and_usage(self) -> None:
        metadata = DocumentMetadataOutput(
            document_type=DocumentTypeEnum.PRICE_REPORT,
            commodity="crude oil",
            language="en",
            business_domain="crude oil trading",
            extraction_strategy="focus on the price table",
            confidence=0.9,
        )
        usage = LLMUsage(prompt_tokens=100, completion_tokens=20, total_tokens=120)
        structured = ScriptedStructuredOutputService(responses=[(metadata, usage)])
        agent = DocumentUnderstandingAgent(
            structured_output_service=structured,  # type: ignore[arg-type]
            prompt_registry=get_extraction_prompt_registry(),
            model="test-model",
            chunks=[_chunk("Brent crude rose to $82.14 per barrel today.")],
        )

        result = await agent.run(_context())

        assert result.metadata == metadata
        assert result.total_usage == usage

    async def test_builds_request_from_sample_of_chunk_text(self) -> None:
        metadata = DocumentMetadataOutput(
            document_type=DocumentTypeEnum.OTHER,
            business_domain="unknown",
            extraction_strategy="n/a",
            confidence=0.1,
        )
        structured = ScriptedStructuredOutputService(responses=[(metadata, LLMUsage())])
        agent = DocumentUnderstandingAgent(
            structured_output_service=structured,  # type: ignore[arg-type]
            prompt_registry=get_extraction_prompt_registry(),
            model="test-model",
            chunks=[_chunk("first chunk text"), _chunk("second chunk text", index=1)],
        )

        await agent.run(_context())

        request = structured.requests[0]
        assert request.model == "test-model"
        assert "first chunk text" in (request.user_prompt or "")
        assert "second chunk text" in (request.user_prompt or "")
        assert request.prompt_package_name == "document_understanding"

    async def test_truncates_sample_to_max_chars(self) -> None:
        metadata = DocumentMetadataOutput(
            document_type=DocumentTypeEnum.OTHER,
            business_domain="unknown",
            extraction_strategy="n/a",
            confidence=0.1,
        )
        structured = ScriptedStructuredOutputService(responses=[(metadata, LLMUsage())])
        huge_chunk = _chunk("word " * 5000)
        agent = DocumentUnderstandingAgent(
            structured_output_service=structured,  # type: ignore[arg-type]
            prompt_registry=get_extraction_prompt_registry(),
            model="test-model",
            chunks=[huge_chunk],
        )

        await agent.run(_context())

        request = structured.requests[0]
        assert len(request.user_prompt or "") < len(huge_chunk.text)

    def test_name_is_stable(self) -> None:
        agent = DocumentUnderstandingAgent(
            structured_output_service=ScriptedStructuredOutputService([]),  # type: ignore[arg-type]
            prompt_registry=get_extraction_prompt_registry(),
            model="m",
            chunks=[],
        )
        assert agent.name == "document_understanding"
