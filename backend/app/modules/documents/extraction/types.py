"""Framework-free result types shared across the extraction sub-package."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class ExtractedPage:
    page_number: int  # 1-indexed
    text: str
    used_ocr: bool
    ocr_confidence: float | None
    header: str | None
    footer: str | None


@dataclass(frozen=True)
class ExtractedTable:
    page_number: int
    rows: list[list[str | None]]


@dataclass(frozen=True)
class DocumentMetadata:
    title: str | None
    author: str | None
    creation_date: datetime | None
    language: str | None
    page_count: int
    word_count: int


@dataclass(frozen=True)
class ExtractionResult:
    pages: list[ExtractedPage]
    tables: list[ExtractedTable] = field(default_factory=list)
    metadata: DocumentMetadata | None = None
