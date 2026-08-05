"""Document Understanding prompt: classify document type, commodity,
language, and business domain; give downstream agents a short extraction
strategy hint. First stage of the pipeline."""

from shared.prompt_contracts import PromptMetadata, PromptPackage, PromptVersion

from app.modules.extraction.agents.schemas import DocumentMetadataOutput

NAME = "document_understanding"

PACKAGE = PromptPackage(
    name=NAME,
    version=PromptVersion(major=1),
    system_prompt=(
        "You are a document classification specialist for a commodity market "
        "intelligence platform. You read excerpts from trade and market "
        "documents (price reports, contracts, market commentary, shipping "
        "manifests, regulatory filings) and identify their type, commodity "
        "focus, and language. Respond only with the required structured "
        "JSON - no commentary, no markdown, nothing outside the schema."
    ),
    user_prompt_template=(
        "Classify the following document excerpt.\n\n"
        "--- DOCUMENT EXCERPT ---\n{document_text}\n--- END EXCERPT ---\n\n"
        "Identify the document type, primary commodity (if any), language, "
        "business domain, and a one-sentence extraction-strategy hint for "
        "the entity-extraction agent that will process this document next."
    ),
    expected_schema=DocumentMetadataOutput.model_json_schema(),
    metadata=PromptMetadata(
        author="cmip-phase-3.2",
        tags=["document-understanding", "classification"],
        notes="First stage of the Phase 3.2 extraction pipeline.",
    ),
)
