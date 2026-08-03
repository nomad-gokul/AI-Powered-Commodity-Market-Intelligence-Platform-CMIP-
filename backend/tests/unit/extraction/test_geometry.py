"""Unit tests for geometry.py against real PDFs drawn with PyMuPDF - not
mocked, same pattern as Phase 2's test_table_extractor.py."""

import io

import fitz

from app.modules.extraction.geometry import (
    PageBlockGeometryExtractor,
    PageGeometryExtractor,
    TableGeometryExtractor,
)


def _pdf_with_two_words() -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "Hello")
    page.insert_text((150, 72), "World")
    buffer = io.BytesIO()
    document.save(buffer)
    document.close()
    return buffer.getvalue()


def _pdf_with_2x2_table() -> bytes:
    document = fitz.open()
    page = document.new_page(width=300, height=200)
    x0, y0, x1, y1 = 50, 50, 250, 150
    xm, ym = (x0 + x1) / 2, (y0 + y1) / 2
    page.draw_rect(fitz.Rect(x0, y0, x1, y1))
    page.draw_line((xm, y0), (xm, y1))
    page.draw_line((x0, ym), (x1, ym))
    page.insert_text((x0 + 10, ym - 10), "Grade")
    page.insert_text((xm + 10, ym - 10), "Price")
    page.insert_text((x0 + 10, y1 - 10), "Brent")
    page.insert_text((xm + 10, y1 - 10), "82.14")
    buffer = io.BytesIO()
    document.save(buffer)
    document.close()
    return buffer.getvalue()


def _blank_pdf() -> bytes:
    document = fitz.open()
    document.new_page()
    buffer = io.BytesIO()
    document.save(buffer)
    document.close()
    return buffer.getvalue()


class TestPageGeometryExtractor:
    def test_extracts_real_word_level_bounding_boxes(self) -> None:
        spans = PageGeometryExtractor().extract(_pdf_with_two_words())
        texts = [s.text for s in spans]
        assert texts == ["Hello", "World"]
        assert all(s.page_number == 1 for s in spans)
        hello = spans[0]
        world = spans[1]
        assert hello.bbox.x1 <= world.bbox.x0  # Hello is measurably to the left of World

    def test_blank_page_returns_no_spans(self) -> None:
        assert PageGeometryExtractor().extract(_blank_pdf()) == []


class TestPageBlockGeometryExtractor:
    def test_extracts_real_text_blocks(self) -> None:
        blocks = PageBlockGeometryExtractor().extract(_pdf_with_two_words())
        assert len(blocks) >= 1
        assert all(b.page_number == 1 for b in blocks)
        assert all(b.bbox.x1 > b.bbox.x0 for b in blocks)

    def test_blank_page_returns_no_blocks(self) -> None:
        assert PageBlockGeometryExtractor().extract(_blank_pdf()) == []


class TestTableGeometryExtractor:
    def test_extracts_real_table_and_cell_bounding_boxes(self) -> None:
        geometries = TableGeometryExtractor().extract(_pdf_with_2x2_table())
        assert len(geometries) == 1
        table = geometries[0]
        assert table.page_number == 1
        assert table.row_count == 2
        assert table.column_count == 2
        assert len(table.cell_bboxes) == 4
        assert table.bbox.x0 == 50.0
        assert table.bbox.x1 == 250.0

    def test_no_table_returns_empty_list(self) -> None:
        assert TableGeometryExtractor().extract(_pdf_with_two_words()) == []
