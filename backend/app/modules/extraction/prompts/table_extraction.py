"""Table Extraction prompt: semantic interpretation of an already-real
table grid (structure/row-column counts come from Phase 2's persisted
extraction or a fresh pdfplumber pass - see TableExtractionAgent). The
LLM never re-derives table structure; it only titles the table and
normalizes each cell's value."""

from shared.prompt_contracts import PromptMetadata, PromptPackage, PromptVersion

from app.modules.extraction.agents.schemas import TableExtractionOutput

NAME = "table_extraction"

PACKAGE = PromptPackage(
    name=NAME,
    version=PromptVersion(major=1),
    system_prompt=(
        "You are a table interpretation specialist for a commodity market "
        "intelligence platform. You are given a table's REAL cell grid, "
        "already correctly structured (do not change the row/column "
        "layout). Your job is purely interpretive: propose a short title/ "
        "caption for the table, and for each cell, provide a best-effort "
        "normalized value (e.g. strip currency symbols and thousands "
        "separators from a price, standardize a unit abbreviation) plus your "
        "confidence (0 to 1). Respond only with the required structured "
        "JSON, addressing every (row, column) pair present in the grid."
    ),
    user_prompt_template=(
        "Table from page {page_number}:\n\n{table_grid}\n\n"
        "Propose a title and normalize each cell's value."
    ),
    expected_schema=TableExtractionOutput.model_json_schema(),
    metadata=PromptMetadata(
        author="cmip-phase-3.2",
        tags=["table-extraction"],
        notes="Invoked once per detected table, not once per document.",
    ),
)
