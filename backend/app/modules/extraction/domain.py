"""Real business logic this module owns: grounding LLM-extracted entities
in actual PDF coordinates rather than trusting an LLM to report a
bounding box it never measured.

Phase 2's persisted extraction output (ExtractedPage/ExtractedTable in
app.modules.documents.extraction.types) discards coordinates entirely -
detect_header_footer() and TableExtractor both compute bounding boxes
internally via PyMuPDF/pdfplumber and throw them away before returning.
So "grounding in real data" here means re-deriving coordinates fresh from
the source PDF (see geometry.py, which uses the same libraries Phase 2
does, through entry points that DO retain position), not reusing anything
Phase 2 persisted - nothing in this file touches Phase 2's frozen module.

Framework-free: no SQLAlchemy, no FastAPI, no PyMuPDF/pdfplumber imports
here - those live in geometry.py. Unit tested standalone.
"""

import hashlib
from dataclasses import dataclass

from app.ai.providers.base import LLMUsage


@dataclass(frozen=True, slots=True)
class BoundingBox:
    x0: float
    y0: float
    x1: float
    y1: float

    def to_json(self) -> dict[str, float]:
        return {"x0": self.x0, "y0": self.y0, "x1": self.x1, "y1": self.y1}

    @staticmethod
    def union(boxes: list["BoundingBox"]) -> "BoundingBox":
        return BoundingBox(
            x0=min(b.x0 for b in boxes),
            y0=min(b.y0 for b in boxes),
            x1=max(b.x1 for b in boxes),
            y1=max(b.y1 for b in boxes),
        )


@dataclass(frozen=True, slots=True)
class PageWordSpan:
    """One word's real position on a page, from a fresh PyMuPDF pass -
    ground truth, never LLM-estimated."""

    page_number: int
    text: str
    bbox: BoundingBox


@dataclass(frozen=True, slots=True)
class PageBlockSpan:
    """One real text block's position - coarser than PageWordSpan (a
    paragraph/line group), used to summarize a page's structure for
    LayoutAgent's LLM call. The same block/bbox concept Phase 2's
    detect_header_footer computes internally and discards - see this
    module's docstring."""

    page_number: int
    block_index: int
    text: str
    bbox: BoundingBox


def build_page_block_summary(
    blocks: list[PageBlockSpan], *, max_pages: int, max_blocks_per_page: int
) -> str:
    """A compact, human-readable summary of real block positions per page,
    for LayoutAgent's LLM call - never raw pixels, never asking the model
    to invent a position. Truncates long documents to the first
    `max_pages` pages and `max_blocks_per_page` blocks per page; the LLM
    call this feeds is for reading-order/column classification, which a
    representative sample establishes just as well as the full document.
    """
    blocks_by_page: dict[int, list[PageBlockSpan]] = {}
    for block in blocks:
        blocks_by_page.setdefault(block.page_number, []).append(block)

    lines: list[str] = []
    for page_number in sorted(blocks_by_page)[:max_pages]:
        lines.append(f"\nPage {page_number}:")
        for block in blocks_by_page[page_number][:max_blocks_per_page]:
            preview = block.text[:80].replace("\n", " ")
            lines.append(
                f"  block_index={block.block_index} "
                f"bbox=({block.bbox.x0:.0f},{block.bbox.y0:.0f},"
                f"{block.bbox.x1:.0f},{block.bbox.y1:.0f}) text={preview!r}"
            )
    return "\n".join(lines) if lines else "(no text blocks found)"


_MAX_MATCH_WINDOW_WORDS = 12


def ground_bounding_box(raw_value: str, spans: list[PageWordSpan]) -> BoundingBox | None:
    """Best-effort: find the shortest contiguous run of `spans` whose
    concatenated text fully contains `raw_value`, case-insensitive and
    whitespace-normalized, and return the union of their real bounding
    boxes.

    Deliberately simple substring matching, not fuzzy/semantic matching -
    an LLM's raw_value for e.g. a price may not tokenize identically to
    the PDF's own word boundaries, so a confident match isn't always
    found. Returns None rather than a wrong guess when it isn't: a null
    bounding_box is honest, a wrong one isn't.

    Only checks "does this window's text contain the target", never the
    reverse ("is this window's text contained in the target") - the
    reverse direction let a single short span (e.g. "Dated") falsely
    match before a longer, correct window (e.g. "Dated Brent") was ever
    tried, since growing window_size is a strictly increasing loop and
    the first match wins.
    """
    target = _normalize(raw_value)
    if not target:
        return None

    max_window = min(len(spans), _MAX_MATCH_WINDOW_WORDS)
    for window_size in range(1, max_window + 1):
        for start in range(0, len(spans) - window_size + 1):
            window = spans[start : start + window_size]
            candidate = _normalize(" ".join(span.text for span in window))
            if candidate and target in candidate:
                return BoundingBox.union([span.bbox for span in window])
    return None


def _normalize(text: str) -> str:
    return " ".join(text.lower().split())


_SURROUNDING_TEXT_WINDOW = 60


def find_mention_context(raw_value: str, chunk_text: str) -> tuple[int | None, str]:
    """Locate `raw_value` within `chunk_text` (case-insensitive) and
    return (character_offset, surrounding_text). If not found - the LLM's
    raw_value doesn't always appear verbatim (it may have lightly
    paraphrased while extracting) - returns (None, raw_value) rather than
    a wrong offset.
    """
    index = chunk_text.lower().find(raw_value.lower())
    if index == -1:
        return None, raw_value
    start = max(0, index - _SURROUNDING_TEXT_WINDOW)
    end = min(len(chunk_text), index + len(raw_value) + _SURROUNDING_TEXT_WINDOW)
    return index, chunk_text[start:end]


def sum_usage(usages: list[LLMUsage]) -> LLMUsage:
    """LLMUsage has no __add__ (it's a plain data container from Phase
    3.1) - agents that make multiple LLM calls (one per chunk, one per
    table) need to aggregate their total for extraction_runs.token_usage,
    so this exists once rather than being reimplemented per agent."""
    return LLMUsage(
        prompt_tokens=sum(u.prompt_tokens for u in usages),
        completion_tokens=sum(u.completion_tokens for u in usages),
        total_tokens=sum(u.total_tokens for u in usages),
    )


def compute_extraction_fingerprint(
    *, document_hash: str, prompt_hash: str, pipeline_version: str, provider: str, model: str
) -> str:
    """Document Hash + Prompt Hash + Pipeline Version + Provider + Model
    (Phase 3.3's spec). Lives here, in extraction's own domain module,
    rather than in the trust submodule that introduced it: deduplicating
    a *trigger_extraction* call is extraction's own lifecycle concern -
    trust/ only reads extraction's already-persisted output, it never
    decides whether an extraction should run again."""
    payload = "|".join([document_hash, prompt_hash, pipeline_version, provider, model])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
