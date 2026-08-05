"""Unit tests for EntityExtractionAgent: one LLM call per chunk,
bounding-box grounding via context.state["layout"], extraction_strategy
read from context.state["document_understanding"]."""

import uuid

from shared.agent_contracts import AgentContext
from shared.ai_contracts import LLMUsage

from app.modules.documents.models import DocumentChunk
from app.modules.extraction.agents.entity_extraction_agent import EntityExtractionAgent
from app.modules.extraction.agents.schemas import (
    BoundingBoxModel,
    DocumentMetadataOutput,
    DocumentTypeEnum,
    DocumentUnderstandingAgentOutput,
    EntityExtractionOutput,
    ExtractedEntityItem,
    LayoutAgentOutput,
    LayoutModel,
    PageSpanModel,
)
from app.modules.extraction.models import EntityType
from app.modules.extraction.prompts import get_extraction_prompt_registry

from ._doubles import ScriptedStructuredOutputService


def _chunk(text: str, *, page_number: int = 1, index: int = 0) -> DocumentChunk:
    return DocumentChunk(
        id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        chunk_index=index,
        page_number=page_number,
        text=text,
        token_count=len(text.split()),
        metadata_json={},
    )


def _context(**state: object) -> AgentContext:
    context = AgentContext(correlation_id="test-correlation")
    context.state.update(state)
    return context


def _entity_item(
    raw_value: str, *, confidence: float = 0.9, normalized_value: str | None = None
) -> ExtractedEntityItem:
    return ExtractedEntityItem(
        entity_type=EntityType.COMMODITY,
        raw_value=raw_value,
        normalized_value=normalized_value,
        confidence=confidence,
    )


class TestRun:
    async def test_returns_grounded_entities_with_chunk_and_page_metadata(self) -> None:
        chunk = _chunk("Brent crude rose to $82.14 per barrel today.")
        output = EntityExtractionOutput(
            entities=[_entity_item("Brent", normalized_value="Brent crude", confidence=0.95)]
        )
        usage = LLMUsage(prompt_tokens=30, completion_tokens=10, total_tokens=40)
        structured = ScriptedStructuredOutputService(responses=[(output, usage)])
        agent = EntityExtractionAgent(
            structured_output_service=structured,  # type: ignore[arg-type]
            prompt_registry=get_extraction_prompt_registry(),
            model="test-model",
            chunks=[chunk],
        )

        result = await agent.run(_context())

        assert len(result.entities) == 1
        entity = result.entities[0]
        assert entity.raw_value == "Brent"
        assert entity.entity_type == EntityType.COMMODITY
        assert entity.page_number == 1
        assert entity.source_chunk_id == chunk.id
        assert result.total_usage == usage

    async def test_grounds_bounding_box_from_layout_spans(self) -> None:
        chunk = _chunk("Brent crude oil.", page_number=1)
        output = EntityExtractionOutput(entities=[_entity_item("Brent")])
        structured = ScriptedStructuredOutputService(responses=[(output, LLMUsage())])
        layout_output = LayoutAgentOutput(
            layout=LayoutModel(pages=[]),
            spans=[
                PageSpanModel(
                    page_number=1, text="Brent", bbox=BoundingBoxModel(x0=1, y0=2, x1=3, y1=4)
                )
            ],
        )
        agent = EntityExtractionAgent(
            structured_output_service=structured,  # type: ignore[arg-type]
            prompt_registry=get_extraction_prompt_registry(),
            model="test-model",
            chunks=[chunk],
        )

        result = await agent.run(_context(layout=layout_output))

        assert result.entities[0].bounding_box == BoundingBoxModel(x0=1, y0=2, x1=3, y1=4)

    async def test_no_layout_in_context_means_no_bounding_box(self) -> None:
        chunk = _chunk("Brent crude oil.")
        output = EntityExtractionOutput(entities=[_entity_item("Brent")])
        structured = ScriptedStructuredOutputService(responses=[(output, LLMUsage())])
        agent = EntityExtractionAgent(
            structured_output_service=structured,  # type: ignore[arg-type]
            prompt_registry=get_extraction_prompt_registry(),
            model="test-model",
            chunks=[chunk],
        )

        result = await agent.run(_context())

        assert result.entities[0].bounding_box is None

    async def test_uses_extraction_strategy_from_document_understanding(self) -> None:
        chunk = _chunk("some text")
        structured = ScriptedStructuredOutputService(
            responses=[(EntityExtractionOutput(entities=[]), LLMUsage())]
        )
        understanding = DocumentUnderstandingAgentOutput(
            metadata=DocumentMetadataOutput(
                document_type=DocumentTypeEnum.PRICE_REPORT,
                business_domain="oil",
                extraction_strategy="focus on prices only",
                confidence=0.9,
            )
        )
        agent = EntityExtractionAgent(
            structured_output_service=structured,  # type: ignore[arg-type]
            prompt_registry=get_extraction_prompt_registry(),
            model="test-model",
            chunks=[chunk],
        )

        await agent.run(_context(document_understanding=understanding))

        assert "focus on prices only" in (structured.requests[0].user_prompt or "")

    async def test_one_llm_call_per_chunk_and_entities_aggregated(self) -> None:
        chunk_a = _chunk("Brent crude.", index=0)
        chunk_b = _chunk("WTI crude.", index=1)
        response_a = EntityExtractionOutput(entities=[_entity_item("Brent")])
        response_b = EntityExtractionOutput(entities=[_entity_item("WTI")])
        structured = ScriptedStructuredOutputService(
            responses=[
                (response_a, LLMUsage(total_tokens=10)),
                (response_b, LLMUsage(total_tokens=20)),
            ]
        )
        agent = EntityExtractionAgent(
            structured_output_service=structured,  # type: ignore[arg-type]
            prompt_registry=get_extraction_prompt_registry(),
            model="test-model",
            chunks=[chunk_a, chunk_b],
        )

        result = await agent.run(_context())

        assert len(structured.requests) == 2
        assert {e.raw_value for e in result.entities} == {"Brent", "WTI"}
        assert result.total_usage.total_tokens == 30

    def test_name_is_stable(self) -> None:
        agent = EntityExtractionAgent(
            structured_output_service=ScriptedStructuredOutputService([]),  # type: ignore[arg-type]
            prompt_registry=get_extraction_prompt_registry(),
            model="m",
            chunks=[],
        )
        assert agent.name == "entity_extraction"
