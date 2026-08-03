"""Real, coordinate-preserving PDF geometry extraction - the ground truth
LayoutAgent and TableExtractionAgent build semantic interpretation on top
of (see domain.py's module docstring for why this re-derives coordinates
rather than reusing Phase 2's persisted output).

Uses the same PyMuPDF/pdfplumber libraries Phase 2 depends on, through
different entry points that retain position: `page.get_text("words")`
instead of `page.get_text("text")`, and `page.find_tables()` (which keeps
each table's own `.bbox`/`.rows[i].cells`) instead of `page.extract_tables()`
(which Phase 2's TableExtractor uses and which returns plain string grids).
"""

import io
from dataclasses import dataclass, field

import fitz  # PyMuPDF
import pdfplumber
from pdfplumber.table import Table as PDFPlumberTable

from app.modules.extraction.domain import BoundingBox, PageBlockSpan, PageWordSpan


class PageGeometryExtractor:
    """Real per-page word-level bounding boxes via PyMuPDF - fine grained,
    used to ground individual entities' bounding boxes (domain.
    ground_bounding_box)."""

    def extract(self, pdf_bytes: bytes) -> list[PageWordSpan]:
        document = fitz.open(stream=pdf_bytes, filetype="pdf")
        try:
            spans: list[PageWordSpan] = []
            for page_index in range(document.page_count):
                page = document.load_page(page_index)
                for word in page.get_text("words"):
                    x0, y0, x1, y1, text = word[0], word[1], word[2], word[3], word[4]
                    if text.strip():
                        spans.append(
                            PageWordSpan(
                                page_number=page_index + 1,
                                text=text,
                                bbox=BoundingBox(x0=x0, y0=y0, x1=x1, y1=y1),
                            )
                        )
            return spans
        finally:
            document.close()


class PageBlockGeometryExtractor:
    """Real per-page text-block bounding boxes via PyMuPDF's block-level
    dict output."""

    def extract(self, pdf_bytes: bytes) -> list[PageBlockSpan]:
        document = fitz.open(stream=pdf_bytes, filetype="pdf")
        try:
            blocks: list[PageBlockSpan] = []
            for page_index in range(document.page_count):
                page = document.load_page(page_index)
                for block_index, block in enumerate(page.get_text("dict")["blocks"]):
                    if block.get("type") != 0:  # not a text block (e.g. an image block)
                        continue
                    text = "".join(
                        span["text"]
                        for line in block.get("lines", [])
                        for span in line.get("spans", [])
                    ).strip()
                    if not text:
                        continue
                    x0, y0, x1, y1 = block["bbox"]
                    blocks.append(
                        PageBlockSpan(
                            page_number=page_index + 1,
                            block_index=block_index,
                            text=text,
                            bbox=BoundingBox(x0=x0, y0=y0, x1=x1, y1=y1),
                        )
                    )
            return blocks
        finally:
            document.close()


@dataclass(frozen=True, slots=True)
class TableGeometry:
    page_number: int
    bbox: BoundingBox
    row_count: int
    column_count: int
    cell_bboxes: dict[tuple[int, int], BoundingBox] = field(default_factory=dict)
    """0-indexed (row, column) -> real bounding box. A missing key means
    that cell is part of a merged region or wasn't confidently detected -
    table_cells.bounding_box is nullable for exactly this reason."""


class TableGeometryExtractor:
    """Real per-table and per-cell bounding boxes via pdfplumber's
    find_tables() - unlike Phase 2's TableExtractor (extract_tables()),
    this retains coordinates."""

    def extract(self, pdf_bytes: bytes) -> list[TableGeometry]:
        results: list[TableGeometry] = []
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page_number, page in enumerate(pdf.pages, start=1):
                for table in page.find_tables():
                    geometry = self._table_geometry(page_number, table)
                    if geometry is not None:
                        results.append(geometry)
        return results

    def _table_geometry(self, page_number: int, table: PDFPlumberTable) -> TableGeometry | None:
        rows = table.rows
        if not rows:
            return None
        cell_bboxes: dict[tuple[int, int], BoundingBox] = {}
        for row_index, row in enumerate(rows):
            for column_index, cell in enumerate(row.cells):
                if cell is not None:
                    x0, top, x1, bottom = cell
                    cell_bboxes[(row_index, column_index)] = BoundingBox(
                        x0=x0, y0=top, x1=x1, y1=bottom
                    )
        column_count = max((column + 1 for (_, column) in cell_bboxes), default=0)
        return TableGeometry(
            page_number=page_number,
            bbox=BoundingBox(*table.bbox),
            row_count=len(rows),
            column_count=column_count,
            cell_bboxes=cell_bboxes,
        )
