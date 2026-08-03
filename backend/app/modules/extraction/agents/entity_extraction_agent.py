"""EntityExtractionAgent: extracts commodity-trading entities from one
document chunk at a time (one LLM call per chunk, not one per document -
chosen so entities stay tied to their source_chunk without a redundant
whole-document pipeline re-run per chunk).

Bounding boxes are never asked of the LLM: after each chunk's entities
come back, this agent matches each entity's raw_value against the real
PyMuPDF word-span geometry LayoutAgent already computed (read from
context.state["layout"]) via domain.ground_bounding_box - best-effort,
None when no confident match, never a guess.
"""

from app.ai.engine.types import AgentContext
from app.ai.prompts.registry import PromptRegistry
from app.ai.providers.base import LLMRequest, LLMUsage
from app.ai.structured.service import StructuredOutputService
from app.modules.documents.models import DocumentChunk
from app.modules.extraction.agents.schemas import (
    BoundingBoxModel,
    DocumentUnderstandingAgentOutput,
    EntityExtractionAgentOutput,
    EntityExtractionOutput,
    GroundedEntity,
    LayoutAgentOutput,
)
from app.modules.extraction.domain import BoundingBox, PageWordSpan, ground_bounding_box, sum_usage


class EntityExtractionAgent:
    def __init__(
        self,
        *,
        structured_output_service: StructuredOutputService,
        prompt_registry: PromptRegistry,
        model: str,
        chunks: list[DocumentChunk],
    ) -> None:
        self._structured = structured_output_service
        self._prompts = prompt_registry
        self._model = model
        self._chunks = chunks

    @property
    def name(self) -> str:
        return "entity_extraction"

    async def run(self, context: AgentContext) -> EntityExtractionAgentOutput:
        extraction_strategy = _read_extraction_strategy(context)
        spans_by_page = _read_spans_by_page(context)

        prompt = self._prompts.get("entity_extraction")
        entities: list[GroundedEntity] = []
        usages: list[LLMUsage] = []

        for chunk in self._chunks:
            system_prompt, user_prompt = prompt.render(
                extraction_strategy=extraction_strategy, chunk_text=chunk.text
            )
            request = LLMRequest(
                model=self._model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                prompt_package_name=prompt.name,
                prompt_package_version=str(prompt.version),
            )
            output, usage = await self._structured.generate_structured_with_usage(
                request, EntityExtractionOutput, correlation_id=context.correlation_id
            )
            usages.append(usage)

            page_spans = spans_by_page.get(chunk.page_number, []) if chunk.page_number else []
            for item in output.entities:
                bbox = ground_bounding_box(item.raw_value, page_spans) if page_spans else None
                entities.append(
                    GroundedEntity(
                        entity_type=item.entity_type,
                        raw_value=item.raw_value,
                        normalized_value=item.normalized_value,
                        confidence=item.confidence,
                        page_number=chunk.page_number,
                        bounding_box=BoundingBoxModel(**bbox.to_json()) if bbox else None,
                        source_chunk_id=chunk.id,
                    )
                )

        return EntityExtractionAgentOutput(entities=entities, total_usage=sum_usage(usages))


def _read_extraction_strategy(context: AgentContext) -> str:
    understanding = context.state.get("document_understanding")
    if isinstance(understanding, DocumentUnderstandingAgentOutput):
        return understanding.metadata.extraction_strategy
    return "Extract every commodity-trading entity present in the text."


def _read_spans_by_page(context: AgentContext) -> dict[int, list[PageWordSpan]]:
    layout = context.state.get("layout")
    spans_by_page: dict[int, list[PageWordSpan]] = {}
    if not isinstance(layout, LayoutAgentOutput):
        return spans_by_page
    for span in layout.spans:
        spans_by_page.setdefault(span.page_number, []).append(
            PageWordSpan(
                page_number=span.page_number,
                text=span.text,
                bbox=BoundingBox(
                    x0=span.bbox.x0, y0=span.bbox.y0, x1=span.bbox.x1, y1=span.bbox.y1
                ),
            )
        )
    return spans_by_page
