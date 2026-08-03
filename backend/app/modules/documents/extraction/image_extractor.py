"""Extraction path for standalone image uploads (PNG/JPG/TIFF) - always
OCR, since there is no PDF text layer to prefer. Produces a single-page
ExtractionResult so the rest of the pipeline (chunking, persistence) can
treat image uploads identically to a one-page PDF.
"""

from app.modules.documents.extraction.types import DocumentMetadata, ExtractedPage, ExtractionResult
from app.modules.documents.ocr.base import OCRProvider


class ImageExtractor:
    def __init__(self, *, ocr_provider: OCRProvider, ocr_language: str) -> None:
        self._ocr_provider = ocr_provider
        self._ocr_language = ocr_language

    async def extract(self, image_bytes: bytes) -> ExtractionResult:
        result = await self._ocr_provider.extract_text(image_bytes, language=self._ocr_language)
        page = ExtractedPage(
            page_number=1,
            text=result.text,
            used_ocr=True,
            ocr_confidence=result.confidence,
            header=None,
            footer=None,
        )
        metadata = DocumentMetadata(
            title=None,
            author=None,
            creation_date=None,
            language=None,
            page_count=1,
            word_count=len(result.text.split()),
        )
        return ExtractionResult(pages=[page], metadata=metadata)
