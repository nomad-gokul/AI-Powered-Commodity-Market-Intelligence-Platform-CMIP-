"""LayoutAgent: computes real per-page word-level bounding boxes via a
fresh PyMuPDF pass (see geometry.py/domain.py for why - Phase 2's
persisted output discards coordinates), then makes ONE LLM call per
document, given a compact summary of real block positions (never raw
pixels), for the genuinely interpretive part: reading order and
multi-column classification.

No LLM call ever sees or invents a coordinate - every bbox in this
agent's output is measured, not guessed.
"""

from app.ai.engine.types import AgentContext
from app.ai.prompts.registry import PromptRegistry
from app.ai.providers.base import LLMRequest
from app.ai.structured.service import StructuredOutputService
from app.modules.extraction.agents.schemas import (
    BoundingBoxModel,
    LayoutAgentOutput,
    LayoutModel,
    PageSpanModel,
)
from app.modules.extraction.domain import build_page_block_summary
from app.modules.extraction.geometry import PageBlockGeometryExtractor, PageGeometryExtractor

_MAX_PAGES_IN_SUMMARY = 5
_MAX_BLOCKS_PER_PAGE_IN_SUMMARY = 40


class LayoutAgent:
    def __init__(
        self,
        *,
        structured_output_service: StructuredOutputService,
        prompt_registry: PromptRegistry,
        model: str,
        pdf_bytes: bytes,
        word_geometry_extractor: PageGeometryExtractor | None = None,
        block_geometry_extractor: PageBlockGeometryExtractor | None = None,
    ) -> None:
        self._structured = structured_output_service
        self._prompts = prompt_registry
        self._model = model
        self._pdf_bytes = pdf_bytes
        self._word_geometry = word_geometry_extractor or PageGeometryExtractor()
        self._block_geometry = block_geometry_extractor or PageBlockGeometryExtractor()

    @property
    def name(self) -> str:
        return "layout"

    async def run(self, context: AgentContext) -> LayoutAgentOutput:
        word_spans = self._word_geometry.extract(self._pdf_bytes)
        block_spans = self._block_geometry.extract(self._pdf_bytes)
        summary = build_page_block_summary(
            block_spans,
            max_pages=_MAX_PAGES_IN_SUMMARY,
            max_blocks_per_page=_MAX_BLOCKS_PER_PAGE_IN_SUMMARY,
        )

        prompt = self._prompts.get("layout_understanding")
        system_prompt, user_prompt = prompt.render(page_block_summary=summary)
        request = LLMRequest(
            model=self._model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            prompt_package_name=prompt.name,
            prompt_package_version=str(prompt.version),
        )
        layout, usage = await self._structured.generate_structured_with_usage(
            request, LayoutModel, correlation_id=context.correlation_id
        )

        span_models = [
            PageSpanModel(
                page_number=span.page_number,
                text=span.text,
                bbox=BoundingBoxModel(
                    x0=span.bbox.x0, y0=span.bbox.y0, x1=span.bbox.x1, y1=span.bbox.y1
                ),
            )
            for span in word_spans
        ]
        return LayoutAgentOutput(layout=layout, spans=span_models, total_usage=usage)
