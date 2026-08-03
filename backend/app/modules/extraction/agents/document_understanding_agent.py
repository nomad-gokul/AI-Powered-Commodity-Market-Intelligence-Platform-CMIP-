"""DocumentUnderstandingAgent: classifies document type, commodity,
language, and business domain from a representative text sample. First
stage of the pipeline - its extraction_strategy hint is read by
EntityExtractionAgent."""

from app.ai.engine.types import AgentContext
from app.ai.prompts.registry import PromptRegistry
from app.ai.providers.base import LLMRequest
from app.ai.structured.service import StructuredOutputService
from app.modules.documents.models import DocumentChunk
from app.modules.extraction.agents.schemas import (
    DocumentMetadataOutput,
    DocumentUnderstandingAgentOutput,
)

_MAX_SAMPLE_CHARS = 8000


def _sample_text(chunks: list[DocumentChunk], *, max_chars: int) -> str:
    """The first N chunks' text, concatenated up to max_chars - a
    representative sample without sending the whole document (which may
    exceed context) just to classify it."""
    parts: list[str] = []
    total = 0
    for chunk in chunks:
        if total >= max_chars:
            break
        parts.append(chunk.text)
        total += len(chunk.text)
    return "\n\n".join(parts)[:max_chars]


class DocumentUnderstandingAgent:
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
        return "document_understanding"

    async def run(self, context: AgentContext) -> DocumentUnderstandingAgentOutput:
        prompt = self._prompts.get("document_understanding")
        system_prompt, user_prompt = prompt.render(
            document_text=_sample_text(self._chunks, max_chars=_MAX_SAMPLE_CHARS)
        )
        request = LLMRequest(
            model=self._model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            prompt_package_name=prompt.name,
            prompt_package_version=str(prompt.version),
        )
        metadata, usage = await self._structured.generate_structured_with_usage(
            request, DocumentMetadataOutput, correlation_id=context.correlation_id
        )
        return DocumentUnderstandingAgentOutput(metadata=metadata, total_usage=usage)
