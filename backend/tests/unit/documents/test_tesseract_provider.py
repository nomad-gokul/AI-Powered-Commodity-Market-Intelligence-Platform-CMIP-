"""Unit tests for TesseractOCRProvider against the real installed Tesseract
binary (not mocked) - see docs/ARCHITECTURE.md for the OCR-provider
strategy this validates. Skipped automatically if Tesseract isn't
reachable, so this suite doesn't break on a machine without it installed.
"""

import io
import shutil

import pytest
from PIL import Image, ImageDraw, ImageFont

from app.core.config import get_settings
from app.modules.documents.ocr.tesseract_provider import TesseractOCRProvider


def _resolve_tesseract_cmd() -> str | None:
    settings = get_settings()
    if settings.ocr_tesseract_cmd:
        return settings.ocr_tesseract_cmd
    return shutil.which("tesseract")


_TESSERACT_CMD = _resolve_tesseract_cmd()

pytestmark = pytest.mark.skipif(
    _TESSERACT_CMD is None, reason="tesseract binary not found - set OCR_TESSERACT_CMD"
)


def _render_text_image(text: str) -> bytes:
    image = Image.new("RGB", (800, 200), color="white")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("arial.ttf", 48)
    except OSError:
        font = ImageFont.load_default()
    draw.text((40, 60), text, fill="black", font=font)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class TestTesseractOCRProvider:
    async def test_extracts_readable_text_from_a_clear_image(self) -> None:
        provider = TesseractOCRProvider(tesseract_cmd=_TESSERACT_CMD)
        image_bytes = _render_text_image("BRENT CRUDE")

        result = await provider.extract_text(image_bytes, language="eng")

        assert "BRENT CRUDE" in result.text.upper()
        assert result.confidence > 0.5

    async def test_blank_image_yields_empty_text(self) -> None:
        provider = TesseractOCRProvider(tesseract_cmd=_TESSERACT_CMD)
        blank = Image.new("RGB", (200, 100), color="white")
        buffer = io.BytesIO()
        blank.save(buffer, format="PNG")

        result = await provider.extract_text(buffer.getvalue(), language="eng")

        assert result.text.strip() == ""
