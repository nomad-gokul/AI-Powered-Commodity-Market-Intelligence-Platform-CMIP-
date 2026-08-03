"""Virus/malware scanning abstraction.

NullVirusScanner is the active implementation this phase - it always
returns a clean verdict. A real scanner (e.g. ClamAV over its daemon
protocol) is future work; this interface exists now so the upload pipeline
already calls a scanner unconditionally, and swapping in a real one later
is a DI change (see api.py's provider wiring), not a pipeline rewrite.
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass


@dataclass(frozen=True)
class ScanResult:
    is_clean: bool
    threat_name: str | None = None


class VirusScanner(ABC):
    @abstractmethod
    async def scan_stream(self, stream: AsyncIterator[bytes]) -> ScanResult:
        """Takes a stream, not bytes: a real engine (e.g. clamd's INSTREAM
        protocol) scans as it reads, so the interface never forces a
        caller to buffer a whole file just to satisfy this method."""
        ...


class NullVirusScanner(VirusScanner):
    """Always reports clean without reading the stream. See module
    docstring for why this is the Phase 2 default rather than a real scan
    engine."""

    async def scan_stream(self, stream: AsyncIterator[bytes]) -> ScanResult:
        return ScanResult(is_clean=True)
