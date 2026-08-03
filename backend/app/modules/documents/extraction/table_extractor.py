"""Table extraction via pdfplumber.

Run over the same PDF bytes as PyMuPDF's text extraction, as a second pass:
pdfplumber's table-detection (ruling-line/whitespace based) is meaningfully
better than PyMuPDF's for the grid-heavy tables common in commodity price
reports, at the cost of being slower - PyMuPDF stays the primary, faster
text extractor for prose. pdfplumber is synchronous/CPU-bound, so the
caller (the worker pipeline) is responsible for running extract() off the
event loop via asyncio.to_thread.
"""

import io

import pdfplumber

from app.modules.documents.extraction.types import ExtractedTable


class TableExtractor:
    def extract(self, pdf_bytes: bytes) -> list[ExtractedTable]:
        tables: list[ExtractedTable] = []
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page_number, page in enumerate(pdf.pages, start=1):
                for raw_table in page.extract_tables():
                    rows = [list(row) for row in raw_table if any(cell for cell in row)]
                    if rows:
                        tables.append(ExtractedTable(page_number=page_number, rows=rows))
        return tables
