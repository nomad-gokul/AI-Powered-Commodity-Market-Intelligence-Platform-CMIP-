"""Layout Understanding prompt: LayoutAgent computes real per-page word/
block bounding boxes deterministically via PyMuPDF (see geometry.py) -
this prompt is used for the one genuinely interpretive judgment a
heuristic can't reliably make: reading order across multi-column layouts
and classifying each block's structural role. The LLM is given a compact
summary of the already-real block positions, never raw pixels, and never
asked to invent coordinates - see domain.py's module docstring."""

from shared.prompt_contracts import PromptMetadata, PromptPackage, PromptVersion

from app.modules.extraction.agents.schemas import LayoutModel

NAME = "layout_understanding"

PACKAGE = PromptPackage(
    name=NAME,
    version=PromptVersion(major=1),
    system_prompt=(
        "You are a document layout analyst. You are given the REAL measured "
        "positions of text blocks on each page (already computed from the "
        "PDF's own coordinate system - you do not need to estimate or invent "
        "any position). Your job is purely interpretive: determine the "
        "semantic reading order, whether the page is multi-column, and each "
        "block's structural role (header, footer, title, body, table "
        "caption, other). Respond only with the required structured JSON."
    ),
    user_prompt_template=(
        "Here is a summary of each page's text blocks, in raw left-to-right, "
        "top-to-bottom order, with their real measured positions:\n\n"
        "{page_block_summary}\n\n"
        "For each page, determine: is it multi-column, how many columns, "
        "and the correct semantic reading order (list of block_index values "
        "in the order a human would actually read them) with each block's "
        "structural role."
    ),
    expected_schema=LayoutModel.model_json_schema(),
    metadata=PromptMetadata(
        author="cmip-phase-3.2",
        tags=["layout", "reading-order"],
        notes=(
            "Only invoked for pages where a deterministic heuristic can't "
            "confidently resolve reading order (multi-column or table-heavy "
            "layouts) - see LayoutAgent."
        ),
    ),
)
