"""Unit tests for paragraph-boundary-aware chunking - no database, no
extraction pipeline, just ExtractedPage -> Chunk."""

import pytest

from app.modules.documents.chunking.chunker import DocumentChunker, count_tokens
from app.modules.documents.extraction.types import ExtractedPage


def _page(page_number: int, text: str) -> ExtractedPage:
    return ExtractedPage(
        page_number=page_number,
        text=text,
        used_ocr=False,
        ocr_confidence=None,
        header=None,
        footer=None,
    )


class TestDocumentChunkerConstruction:
    def test_rejects_non_positive_chunk_size(self) -> None:
        with pytest.raises(ValueError, match="chunk_size_tokens"):
            DocumentChunker(chunk_size_tokens=0, chunk_overlap_tokens=0)

    def test_rejects_overlap_greater_than_or_equal_to_size(self) -> None:
        with pytest.raises(ValueError, match="chunk_overlap_tokens"):
            DocumentChunker(chunk_size_tokens=100, chunk_overlap_tokens=100)


class TestChunking:
    def test_empty_pages_produce_no_chunks(self) -> None:
        chunker = DocumentChunker(chunk_size_tokens=500, chunk_overlap_tokens=50)
        assert chunker.chunk([_page(1, "")]) == []

    def test_short_document_is_a_single_chunk(self) -> None:
        chunker = DocumentChunker(chunk_size_tokens=500, chunk_overlap_tokens=50)
        chunks = chunker.chunk([_page(1, "This is a short paragraph.\n\nAnd a second one.")])
        assert len(chunks) == 1
        assert chunks[0].chunk_index == 0
        assert chunks[0].page_number == 1
        assert "short paragraph" in chunks[0].text
        assert "second one" in chunks[0].text

    def test_paragraphs_never_split_within_a_chunk_size_budget(self) -> None:
        # Two paragraphs that individually fit but together exceed a small
        # budget must land in separate chunks, each fully intact.
        paragraph_a = "Alpha. " * 40
        paragraph_b = "Beta. " * 40
        chunker = DocumentChunker(chunk_size_tokens=60, chunk_overlap_tokens=5)
        chunks = chunker.chunk([_page(1, f"{paragraph_a}\n\n{paragraph_b}")])
        assert len(chunks) >= 2
        assert "Alpha." in chunks[0].text
        assert "Beta." not in chunks[0].text

    def test_no_chunk_exceeds_roughly_size_plus_overlap(self) -> None:
        long_text = "\n\n".join(f"Paragraph number {i} with some words in it." for i in range(200))
        chunker = DocumentChunker(chunk_size_tokens=100, chunk_overlap_tokens=20)
        chunks = chunker.chunk([_page(1, long_text)])
        for chunk in chunks:
            # generous slack for one paragraph landing over budget
            assert count_tokens(chunk.text) <= 100 + 20 + 30

    def test_overlap_repeats_trailing_content_in_next_chunk(self) -> None:
        # Each paragraph must be small enough, on its own, to fit inside
        # the overlap budget - otherwise _carry_overlap carries nothing.
        paragraphs = [f"Paragraph {i}." for i in range(20)]
        chunker = DocumentChunker(chunk_size_tokens=30, chunk_overlap_tokens=15)
        chunks = chunker.chunk([_page(1, "\n\n".join(paragraphs))])
        assert len(chunks) >= 2
        # The tail of chunk N should reappear at the head of chunk N+1.
        overlap_candidate = chunks[0].text.split("\n\n")[-1]
        assert overlap_candidate in chunks[1].text

    def test_multi_page_document_tags_chunk_with_starting_page(self) -> None:
        chunker = DocumentChunker(chunk_size_tokens=500, chunk_overlap_tokens=50)
        chunks = chunker.chunk([_page(1, "Page one text."), _page(2, "Page two text.")])
        assert len(chunks) == 1
        assert chunks[0].page_number == 1
        assert chunks[0].metadata.get("source_pages") == [1, 2]

    def test_single_page_chunk_has_no_source_pages_metadata(self) -> None:
        chunker = DocumentChunker(chunk_size_tokens=500, chunk_overlap_tokens=50)
        chunks = chunker.chunk([_page(1, "Only one page of text here.")])
        assert chunks[0].metadata == {}

    def test_oversized_single_paragraph_is_split_at_sentence_boundaries(self) -> None:
        sentence = "This is one sentence with a reasonable number of words in it. "
        huge_paragraph = sentence * 30  # a single "paragraph" (no blank lines) way over budget
        chunker = DocumentChunker(chunk_size_tokens=50, chunk_overlap_tokens=5)
        chunks = chunker.chunk([_page(1, huge_paragraph)])
        assert len(chunks) > 1
        for chunk in chunks:
            assert count_tokens(chunk.text) <= 50 + 5 + 20

    def test_pathological_text_with_no_punctuation_still_terminates(self) -> None:
        # Hard token-level splitting is approximate at chunk boundaries
        # (decode+re-encode of a partial token stream isn't guaranteed to
        # round-trip to an identical count) - what's guaranteed is that it
        # terminates and stays within the size+overlap budget, not an
        # exact token-count reconstruction.
        garbled = "word " * 500  # no sentence punctuation at all
        chunker = DocumentChunker(chunk_size_tokens=30, chunk_overlap_tokens=5)
        chunks = chunker.chunk([_page(1, garbled)])
        assert len(chunks) > 1
        for chunk in chunks:
            assert count_tokens(chunk.text) <= 30 + 5 + 10

    def test_chunk_indices_are_sequential(self) -> None:
        long_text = "\n\n".join(f"Paragraph number {i} with some words in it." for i in range(200))
        chunker = DocumentChunker(chunk_size_tokens=80, chunk_overlap_tokens=10)
        chunks = chunker.chunk([_page(1, long_text)])
        assert [c.chunk_index for c in chunks] == list(range(len(chunks)))


class TestCountTokens:
    def test_empty_string_is_zero_tokens(self) -> None:
        assert count_tokens("") == 0

    def test_longer_text_has_more_tokens(self) -> None:
        assert count_tokens("one two three four five") > count_tokens("one two")
