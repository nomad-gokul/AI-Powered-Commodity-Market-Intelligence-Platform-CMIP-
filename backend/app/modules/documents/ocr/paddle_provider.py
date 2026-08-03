"""PaddleOCR-backed OCRProvider.

Implemented against the real PaddleOCR API (paddleocr.PaddleOCR(...).ocr()),
but this class is NOT exercised by this repository's test suite and has NOT
been run end-to-end in this development environment: paddlepaddle's Windows
wheel is unreliable to install here, so it could not be verified for real
(see docs/ARCHITECTURE.md). Requires the optional extra:

    pip install "cmip-backend[paddleocr]"

Verify it in a Linux/Docker environment before relying on it in production;
TesseractOCRProvider is the default and the only OCR provider this codebase
currently claims test coverage for.
"""

import asyncio
import io
from functools import lru_cache
from typing import Any

from PIL import Image

from app.modules.documents.ocr.base import OCRProvider, OCRResult


@lru_cache
def _get_engine(language: str) -> Any:
    from paddleocr import PaddleOCR  # optional dependency - see module docstring

    return PaddleOCR(use_angle_cls=True, lang=language, show_log=False)


class PaddleOCRProvider(OCRProvider):
    def __init__(self, *, language: str = "en") -> None:
        self._language = language

    async def extract_text(self, image_bytes: bytes, *, language: str) -> OCRResult:
        return await asyncio.to_thread(self._extract_sync, image_bytes, language or self._language)

    def _extract_sync(self, image_bytes: bytes, language: str) -> OCRResult:
        import numpy as np  # optional dependency - see module docstring

        engine = _get_engine(language)
        image_array = np.array(Image.open(io.BytesIO(image_bytes)).convert("RGB"))
        result = engine.ocr(image_array, cls=True)

        lines = result[0] if result else []
        texts: list[str] = []
        confidences: list[float] = []
        for _bbox, (text, confidence) in lines:
            texts.append(text)
            confidences.append(float(confidence))

        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0
        return OCRResult(text=" ".join(texts), confidence=avg_confidence)
