"""Unit tests for ImageExtractor - the standalone-image (PNG/JPG/TIFF)
extraction path, always OCR since there is no PDF text layer."""

from app.modules.documents.extraction.image_extractor import ImageExtractor
from app.modules.documents.ocr.base import OCRProvider, OCRResult


class FakeOCRProvider(OCRProvider):
    def __init__(self, text: str, confidence: float) -> None:
        self.text = text
        self.confidence = confidence

    async def extract_text(self, image_bytes: bytes, *, language: str) -> OCRResult:
        return OCRResult(text=self.text, confidence=self.confidence)


class TestImageExtractor:
    async def test_produces_a_single_page_result(self) -> None:
        extractor = ImageExtractor(
            ocr_provider=FakeOCRProvider("scanned invoice text", 0.87), ocr_language="eng"
        )
        result = await extractor.extract(b"fake-image-bytes")

        assert len(result.pages) == 1
        assert result.pages[0].page_number == 1
        assert result.pages[0].used_ocr is True
        assert result.pages[0].text == "scanned invoice text"
        assert result.pages[0].ocr_confidence == 0.87

    async def test_metadata_reflects_single_page_and_word_count(self) -> None:
        extractor = ImageExtractor(
            ocr_provider=FakeOCRProvider("one two three", 0.5), ocr_language="eng"
        )
        result = await extractor.extract(b"fake-image-bytes")

        assert result.metadata is not None
        assert result.metadata.page_count == 1
        assert result.metadata.word_count == 3
