"""Tesseract-backed OCRProvider - the default, tested implementation.

pytesseract shells out to the tesseract binary synchronously, so the call
is pushed onto a worker thread via asyncio.to_thread to avoid blocking the
event loop (this runs inside an ARQ worker process, not the API process,
but the same rule applies - ARQ workers are asyncio-based too).
"""

import asyncio
import io

import pytesseract
from PIL import Image

from app.modules.documents.ocr.base import OCRProvider, OCRResult


class TesseractOCRProvider(OCRProvider):
    def __init__(self, *, tesseract_cmd: str | None = None) -> None:
        if tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

    async def extract_text(self, image_bytes: bytes, *, language: str) -> OCRResult:
        return await asyncio.to_thread(self._extract_sync, image_bytes, language)

    def _extract_sync(self, image_bytes: bytes, language: str) -> OCRResult:
        image = Image.open(io.BytesIO(image_bytes))
        data = pytesseract.image_to_data(image, lang=language, output_type=pytesseract.Output.DICT)

        words: list[str] = []
        confidences: list[float] = []
        for text, conf in zip(data["text"], data["conf"], strict=True):
            stripped = text.strip()
            if not stripped:
                continue
            words.append(stripped)
            conf_value = float(conf)
            if conf_value >= 0:
                confidences.append(conf_value)

        avg_confidence = (sum(confidences) / len(confidences) / 100.0) if confidences else 0.0
        return OCRResult(text=" ".join(words), confidence=avg_confidence)
