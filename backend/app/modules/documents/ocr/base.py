"""OCRProvider abstraction: extracts text from a single page image or a
standalone scanned image file. The extraction pipeline always prefers
native PDF text extraction (PyMuPDF) first - OCR only runs on a page whose
native text is empty/near-empty, or on an image-only upload.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class OCRResult:
    text: str
    confidence: float  # 0.0-1.0, provider-reported average word confidence


class OCRProvider(ABC):
    @abstractmethod
    async def extract_text(self, image_bytes: bytes, *, language: str) -> OCRResult: ...
