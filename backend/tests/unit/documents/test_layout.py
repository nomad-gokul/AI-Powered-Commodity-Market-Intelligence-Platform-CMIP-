"""Unit tests for the header/footer detection heuristic, using real
PyMuPDF-rendered pages (not mocked) so the bounding-box math is exercised
for real."""

import fitz

from app.modules.documents.extraction.layout import detect_header_footer


def _build_page(lines: list[tuple[str, float]]) -> fitz.Page:
    """`lines` is a list of (text, y_position) - y=0 is the top of the page."""
    document = fitz.open()
    page = document.new_page(width=612, height=792)  # US letter
    for text, y in lines:
        page.insert_text((72, y), text)
    return page


class TestDetectHeaderFooter:
    def test_text_at_top_of_page_is_a_header(self) -> None:
        page = _build_page([("Platts Dated Brent Assessment", 20)])
        header, footer = detect_header_footer(page)
        assert header is not None
        assert "Platts Dated Brent" in header
        assert footer is None

    def test_text_at_bottom_of_page_is_a_footer(self) -> None:
        page = _build_page([("Page 1 of 12 - Copyright 2026", 780)])
        header, footer = detect_header_footer(page)
        assert footer is not None
        assert "Copyright" in footer
        assert header is None

    def test_text_in_body_of_page_is_neither(self) -> None:
        page = _build_page([("This is the main body text of the report.", 400)])
        header, footer = detect_header_footer(page)
        assert header is None
        assert footer is None

    def test_blank_page_has_no_header_or_footer(self) -> None:
        document = fitz.open()
        page = document.new_page(width=612, height=792)
        header, footer = detect_header_footer(page)
        assert header is None
        assert footer is None
