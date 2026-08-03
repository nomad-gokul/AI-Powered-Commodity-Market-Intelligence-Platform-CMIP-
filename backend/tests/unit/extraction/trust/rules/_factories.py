"""Shared in-memory entity/table/cell factories for rule unit tests -
plain ORM object construction (never persisted), so tests stay fast and
need no database."""

import uuid

from app.modules.extraction.models import EntityType, ExtractedEntity, ExtractedTable, TableCell


def make_entity(
    *,
    entity_type: EntityType,
    raw_value: str,
    normalized_value: str | None = None,
    page_number: int | None = 1,
    bounding_box: dict[str, float] | None = None,
    confidence: float = 0.9,
) -> ExtractedEntity:
    return ExtractedEntity(
        id=uuid.uuid4(),
        extraction_run_id=uuid.uuid4(),
        entity_type=entity_type,
        raw_value=raw_value,
        normalized_value=normalized_value,
        confidence=confidence,
        page_number=page_number,
        bounding_box=bounding_box,
        provider="groq",
        model="test-model",
        prompt_version="1.0",
    )


def make_table(*, page_number: int = 1, confidence: float = 0.9) -> ExtractedTable:
    return ExtractedTable(
        id=uuid.uuid4(),
        extraction_run_id=uuid.uuid4(),
        page_number=page_number,
        title=None,
        confidence=confidence,
        row_count=0,
        column_count=0,
        metadata_json={},
    )


def make_cell(
    *, table_id: uuid.UUID, row: int, column: int, raw_value: str | None, confidence: float = 0.9
) -> TableCell:
    return TableCell(
        id=uuid.uuid4(),
        table_id=table_id,
        row=row,
        column=column,
        raw_value=raw_value,
        normalized_value=raw_value,
        confidence=confidence,
    )
