"""Unit tests for TableExtractor against a real ruling-line grid drawn with
PyMuPDF and parsed with pdfplumber - not mocked."""

import io

import fitz

from app.modules.documents.extraction.table_extractor import TableExtractor


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


def _pdf_without_tables() -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 100), "Just prose, no ruling lines or grid at all.")
    buffer = io.BytesIO()
    document.save(buffer)
    document.close()
    return buffer.getvalue()


class TestTableExtractor:
    def test_extracts_a_real_grid_table(self) -> None:
        tables = TableExtractor().extract(_pdf_with_2x2_table())
        assert len(tables) == 1
        assert tables[0].page_number == 1
        assert tables[0].rows == [["Grade", "Price"], ["Brent", "82.14"]]

    def test_document_without_tables_returns_empty_list(self) -> None:
        assert TableExtractor().extract(_pdf_without_tables()) == []
