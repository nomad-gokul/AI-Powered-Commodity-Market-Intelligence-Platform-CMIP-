"""Entity Extraction prompt: extract commodity-trading entities from one
document chunk at a time (see EntityExtractionAgent for why chunk
granularity). Bounding boxes are never asked of the LLM - they're resolved
afterward by matching raw_value against real PyMuPDF word-span geometry
(domain.ground_bounding_box)."""

from shared.prompt_contracts import PromptMetadata, PromptPackage, PromptVersion

from app.modules.extraction.agents.schemas import EntityExtractionOutput
from app.modules.extraction.models import EntityType

_ENTITY_TYPES = ", ".join(sorted(e.value for e in EntityType))

NAME = "entity_extraction"

PACKAGE = PromptPackage(
    name=NAME,
    version=PromptVersion(major=1),
    system_prompt=(
        "You are an entity extraction specialist for a commodity market "
        "intelligence platform. Extract every mention of the following "
        f"entity types from the given text: {_ENTITY_TYPES}. For each "
        "entity, report the exact raw text as it appears (raw_value), your "
        "best-effort normalized form (normalized_value - e.g. 'USD' for "
        "'$', an ISO date for a written date), and your confidence (0 to 1) "
        "that this is a correct extraction. Do not invent entities that "
        "aren't in the text. Respond only with the required structured JSON."
    ),
    user_prompt_template=(
        "{extraction_strategy}\n\n--- TEXT ---\n{chunk_text}\n--- END TEXT ---\n\n"
        "Extract every commodity-trading entity mentioned above."
    ),
    expected_schema=EntityExtractionOutput.model_json_schema(),
    metadata=PromptMetadata(
        author="cmip-phase-3.2",
        tags=["entity-extraction"],
        notes="Invoked once per DocumentChunk, not once per document.",
    ),
)
