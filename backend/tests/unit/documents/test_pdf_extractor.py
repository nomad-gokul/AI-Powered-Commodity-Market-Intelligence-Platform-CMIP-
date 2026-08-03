"""Unit tests for PDFExtractor against real PyMuPDF-generated PDFs. The OCR
fallback path uses a FakeOCRProvider (no real Tesseract call) so this stays
a fast, deterministic unit test - the real Tesseract integration is
exercised in tests/integration/test_worker_pipeline.py."""

import io

import fitz
import pytest

from app.modules.documents.extraction.pdf_extractor import PDFExtractor
from app.modules.documents.ocr.base import OCRProvider, OCRResult


class FakeOCRProvider(OCRProvider):
    def __init__(self, text: str = "OCR extracted text", confidence: float = 0.9) -> None:
        self.text = text
        self.confidence = confidence
        self.calls = 0

    async def extract_text(self, image_bytes: bytes, *, language: str) -> OCRResult:
        self.calls += 1
        return OCRResult(text=self.text, confidence=self.confidence)


def _pdf_with_native_text(
    text: str, *, title: str | None = None, author: str | None = None
) -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 100), text)
    if title or author:
        document.set_metadata({"title": title or "", "author": author or ""})
    buffer = io.BytesIO()
    document.save(buffer)
    document.close()
    return buffer.getvalue()


def _blank_pdf(page_count: int = 1) -> bytes:
    document = fitz.open()
    for _ in range(page_count):
        document.new_page()
    buffer = io.BytesIO()
    document.save(buffer)
    document.close()
    return buffer.getvalue()


class TestNativeTextExtraction:
    async def test_extracts_native_text_without_calling_ocr(self) -> None:
        pdf_bytes = _pdf_with_native_text(
            "This is a genuine native PDF text layer with plenty of characters."
        )
        ocr = FakeOCRProvider()
        extractor = PDFExtractor(ocr_provider=ocr, ocr_language="eng", min_native_chars_per_page=20)

        result = await extractor.extract(pdf_bytes)

        assert len(result.pages) == 1
        assert "genuine native PDF text" in result.pages[0].text
        assert result.pages[0].used_ocr is False
        assert ocr.calls == 0

    async def test_metadata_includes_title_and_author(self) -> None:
        pdf_bytes = _pdf_with_native_text(
            "Report body text with enough characters to skip OCR entirely.",
            title="Dated Brent Assessment",
            author="Platts",
        )
        extractor = PDFExtractor(
            ocr_provider=FakeOCRProvider(), ocr_language="eng", min_native_chars_per_page=20
        )

        result = await extractor.extract(pdf_bytes)

        assert result.metadata is not None
        assert result.metadata.title == "Dated Brent Assessment"
        assert result.metadata.author == "Platts"
        assert result.metadata.page_count == 1

    async def test_word_count_reflects_extracted_text(self) -> None:
        pdf_bytes = _pdf_with_native_text("one two three four five six seven eight nine ten")
        extractor = PDFExtractor(
            ocr_provider=FakeOCRProvider(), ocr_language="eng", min_native_chars_per_page=5
        )
        result = await extractor.extract(pdf_bytes)
        assert result.metadata is not None
        assert result.metadata.word_count == 10


class TestOCRFallback:
    async def test_blank_page_triggers_ocr(self) -> None:
        pdf_bytes = _blank_pdf()
        ocr = FakeOCRProvider(text="scanned page text")
        extractor = PDFExtractor(ocr_provider=ocr, ocr_language="eng", min_native_chars_per_page=20)

        result = await extractor.extract(pdf_bytes)

        assert ocr.calls == 1
        assert result.pages[0].used_ocr is True
        assert result.pages[0].text == "scanned page text"
        assert result.pages[0].ocr_confidence == pytest.approx(0.9)

    async def test_ocr_language_is_passed_through(self) -> None:
        pdf_bytes = _blank_pdf()

        class LanguageCapturingOCR(OCRProvider):
            captured_language: str | None = None

            async def extract_text(self, image_bytes: bytes, *, language: str) -> OCRResult:
                self.captured_language = language
                return OCRResult(text="x", confidence=1.0)

        ocr = LanguageCapturingOCR()
        extractor = PDFExtractor(ocr_provider=ocr, ocr_language="fra", min_native_chars_per_page=20)
        await extractor.extract(pdf_bytes)
        assert ocr.captured_language == "fra"

    async def test_mixed_document_only_ocrs_the_blank_page(self) -> None:
        document = fitz.open()
        native_page = document.new_page()
        native_page.insert_text((72, 100), "Plenty of native text on this page to avoid OCR.")
        document.new_page()  # second page is blank -> needs OCR
        buffer = io.BytesIO()
        document.save(buffer)
        document.close()

        ocr = FakeOCRProvider(text="ocr text")
        extractor = PDFExtractor(ocr_provider=ocr, ocr_language="eng", min_native_chars_per_page=20)
        result = await extractor.extract(buffer.getvalue())

        assert len(result.pages) == 2
        assert result.pages[0].used_ocr is False
        assert result.pages[1].used_ocr is True
        assert ocr.calls == 1


class TestPageCount:
    async def test_multi_page_document_extracts_all_pages(self) -> None:
        pdf_bytes = _blank_pdf(page_count=3)
        extractor = PDFExtractor(
            ocr_provider=FakeOCRProvider(), ocr_language="eng", min_native_chars_per_page=20
        )
        result = await extractor.extract(pdf_bytes)
        assert len(result.pages) == 3
        assert [p.page_number for p in result.pages] == [1, 2, 3]
