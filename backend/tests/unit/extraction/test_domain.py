"""Unit tests for extraction/domain.py's pure functions: bounding-box
grounding, layout summarization, mention-context lookup, usage summation.
No I/O, no PyMuPDF/pdfplumber - those are geometry.py's job."""

from app.ai.providers.base import LLMUsage
from app.modules.extraction.domain import (
    BoundingBox,
    PageBlockSpan,
    PageWordSpan,
    build_page_block_summary,
    find_mention_context,
    ground_bounding_box,
    sum_usage,
)


def _span(text: str, x0: float, page: int = 1) -> PageWordSpan:
    bbox = BoundingBox(x0=x0, y0=0, x1=x0 + 10, y1=10)
    return PageWordSpan(page_number=page, text=text, bbox=bbox)


class TestBoundingBoxUnion:
    def test_union_of_single_box_is_itself(self) -> None:
        box = BoundingBox(x0=1, y0=2, x1=3, y1=4)
        assert BoundingBox.union([box]) == box

    def test_union_spans_the_extremes_of_all_boxes(self) -> None:
        boxes = [BoundingBox(0, 0, 10, 10), BoundingBox(20, 5, 30, 15)]
        result = BoundingBox.union(boxes)
        assert result == BoundingBox(x0=0, y0=0, x1=30, y1=15)

    def test_to_json_round_trips_fields(self) -> None:
        box = BoundingBox(x0=1.5, y0=2.5, x1=3.5, y1=4.5)
        assert box.to_json() == {"x0": 1.5, "y0": 2.5, "x1": 3.5, "y1": 4.5}


class TestGroundBoundingBox:
    def test_single_word_exact_match(self) -> None:
        spans = [_span("Brent", 0), _span("82.14", 20)]
        result = ground_bounding_box("Brent", spans)
        assert result == BoundingBox(x0=0, y0=0, x1=10, y1=10)

    def test_multi_word_match_unions_the_matched_spans(self) -> None:
        spans = [_span("Dated", 0), _span("Brent", 20), _span("Crude", 40)]
        result = ground_bounding_box("Dated Brent", spans)
        assert result == BoundingBox(x0=0, y0=0, x1=30, y1=10)

    def test_case_insensitive_match(self) -> None:
        spans = [_span("BRENT", 0)]
        assert ground_bounding_box("brent", spans) is not None

    def test_no_match_returns_none(self) -> None:
        spans = [_span("Brent", 0)]
        assert ground_bounding_box("Nonexistent", spans) is None

    def test_empty_raw_value_returns_none(self) -> None:
        spans = [_span("Brent", 0)]
        assert ground_bounding_box("", spans) is None

    def test_empty_spans_returns_none(self) -> None:
        assert ground_bounding_box("Brent", []) is None

    def test_substring_match_within_a_single_span(self) -> None:
        spans = [_span("USD/MT", 0)]
        assert ground_bounding_box("USD", spans) is not None


class TestFindMentionContext:
    def test_finds_offset_and_surrounding_text(self) -> None:
        text = "The price of Brent crude rose to 82.14 today."
        offset, surrounding = find_mention_context("Brent", text)
        assert offset == text.lower().index("brent")
        assert "Brent" in surrounding

    def test_case_insensitive(self) -> None:
        text = "the PRICE of brent crude"
        offset, _ = find_mention_context("Brent", text)
        assert offset == text.lower().index("brent")

    def test_not_found_returns_none_offset_and_raw_value_as_surrounding(self) -> None:
        offset, surrounding = find_mention_context("Nonexistent", "some other text")
        assert offset is None
        assert surrounding == "Nonexistent"

    def test_surrounding_text_is_windowed_not_the_whole_chunk(self) -> None:
        text = "x" * 200 + "Brent" + "y" * 200
        _, surrounding = find_mention_context("Brent", text)
        assert len(surrounding) < len(text)
        assert "Brent" in surrounding


class TestSumUsage:
    def test_sums_across_multiple_usages(self) -> None:
        usages = [
            LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            LLMUsage(prompt_tokens=20, completion_tokens=8, total_tokens=28),
        ]
        result = sum_usage(usages)
        assert result == LLMUsage(prompt_tokens=30, completion_tokens=13, total_tokens=43)

    def test_empty_list_returns_zero_usage(self) -> None:
        assert sum_usage([]) == LLMUsage()


_TINY_BBOX = BoundingBox(0, 0, 10, 10)


class TestBuildPageBlockSummary:
    def test_groups_blocks_by_page(self) -> None:
        blocks = [
            PageBlockSpan(page_number=1, block_index=0, text="Header", bbox=_TINY_BBOX),
            PageBlockSpan(page_number=2, block_index=0, text="Page 2 text", bbox=_TINY_BBOX),
        ]
        summary = build_page_block_summary(blocks, max_pages=5, max_blocks_per_page=40)
        assert "Page 1:" in summary
        assert "Page 2:" in summary
        assert "Header" in summary
        assert "Page 2 text" in summary

    def test_truncates_to_max_pages(self) -> None:
        blocks = [
            PageBlockSpan(page_number=p, block_index=0, text="x", bbox=_TINY_BBOX)
            for p in range(1, 10)
        ]
        summary = build_page_block_summary(blocks, max_pages=2, max_blocks_per_page=40)
        assert "Page 1:" in summary
        assert "Page 2:" in summary
        assert "Page 3:" not in summary

    def test_truncates_to_max_blocks_per_page(self) -> None:
        blocks = [
            PageBlockSpan(page_number=1, block_index=i, text=f"block-{i}", bbox=_TINY_BBOX)
            for i in range(10)
        ]
        summary = build_page_block_summary(blocks, max_pages=5, max_blocks_per_page=3)
        assert "block-0" in summary
        assert "block-3" not in summary

    def test_no_blocks_returns_placeholder(self) -> None:
        summary = build_page_block_summary([], max_pages=5, max_blocks_per_page=40)
        assert summary == "(no text blocks found)"
