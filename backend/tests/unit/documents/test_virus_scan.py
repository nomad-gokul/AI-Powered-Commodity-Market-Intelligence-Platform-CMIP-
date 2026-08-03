"""Unit test for the virus scan interface's Phase 2 implementation."""

from collections.abc import AsyncIterator

from app.modules.documents.security.virus_scan import NullVirusScanner


async def _stream() -> AsyncIterator[bytes]:
    yield b"anything"


class TestNullVirusScanner:
    async def test_always_reports_clean(self) -> None:
        result = await NullVirusScanner().scan_stream(_stream())
        assert result.is_clean is True
        assert result.threat_name is None
