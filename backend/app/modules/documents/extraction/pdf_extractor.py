"""Native PDF text/metadata extraction via PyMuPDF, with OCR fallback for
pages that have no usable native text (scanned pages inside an otherwise
digital-native PDF - the common case for a mixed report with a scanned
cover page or exhibit).

Native extraction is always attempted first and OCR only runs on pages
that need it - OCR is slow and lossy compared to a PDF's embedded text
layer, so paying for it unconditionally would be wasteful and would
degrade quality on pages that didn't need it.
"""

import re
from datetime import UTC, datetime

import fitz  # PyMuPDF
from langdetect import LangDetectException, detect

from app.modules.documents.extraction.layout import detect_header_footer
from app.modules.documents.extraction.types import DocumentMetadata, ExtractedPage, ExtractionResult
from app.modules.documents.ocr.base import OCRProvider

_PDF_DATE_RE = re.compile(
    r"D:(?P<year>\d{4})(?P<month>\d{2})(?P<day>\d{2})"
    r"(?P<hour>\d{2})?(?P<minute>\d{2})?(?P<second>\d{2})?"
)


def _parse_pdf_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    match = _PDF_DATE_RE.match(raw)
    if match is None:
        return None
    parts = match.groupdict(default="00")
    try:
        return datetime(
            int(parts["year"]),
            int(parts["month"]),
            int(parts["day"]),
            int(parts["hour"]),
            int(parts["minute"]),
            int(parts["second"]),
            tzinfo=UTC,
        )
    except ValueError:
        return None


def _detect_language(sample_text: str) -> str | None:
    stripped = sample_text.strip()
    if len(stripped) < 20:  # too short for a reliable guess
        return None
    try:
        return str(detect(stripped))
    except LangDetectException:
        return None


class PDFExtractor:
    def __init__(
        self,
        *,
        ocr_provider: OCRProvider,
        ocr_language: str,
        min_native_chars_per_page: int,
    ) -> None:
        self._ocr_provider = ocr_provider
        self._ocr_language = ocr_language
        self._min_native_chars_per_page = min_native_chars_per_page

    async def extract(self, pdf_bytes: bytes) -> ExtractionResult:
        document = fitz.open(stream=pdf_bytes, filetype="pdf")
        try:
            pages = [
                await self._extract_page(document, index) for index in range(document.page_count)
            ]
            metadata = self._build_metadata(document, pages)
            return ExtractionResult(pages=pages, metadata=metadata)
        finally:
            document.close()

    async def _extract_page(self, document: fitz.Document, page_index: int) -> ExtractedPage:
        page = document.load_page(page_index)
        page_number = page_index + 1
        header, footer = detect_header_footer(page)
        native_text = page.get_text("text").strip()

        if len(native_text) >= self._min_native_chars_per_page:
            return ExtractedPage(
                page_number=page_number,
                text=native_text,
                used_ocr=False,
                ocr_confidence=None,
                header=header,
                footer=footer,
            )

        pixmap = page.get_pixmap(dpi=200)
        image_bytes = pixmap.tobytes("png")
        ocr_result = await self._ocr_provider.extract_text(image_bytes, language=self._ocr_language)
        return ExtractedPage(
            page_number=page_number,
            text=ocr_result.text,
            used_ocr=True,
            ocr_confidence=ocr_result.confidence,
            header=header,
            footer=footer,
        )

    def _build_metadata(
        self, document: fitz.Document, pages: list[ExtractedPage]
    ) -> DocumentMetadata:
        raw_metadata = document.metadata or {}
        full_text = " ".join(page.text for page in pages)
        return DocumentMetadata(
            title=raw_metadata.get("title") or None,
            author=raw_metadata.get("author") or None,
            creation_date=_parse_pdf_date(raw_metadata.get("creationDate")),
            language=_detect_language(full_text),
            page_count=document.page_count,
            word_count=len(full_text.split()),
        )
