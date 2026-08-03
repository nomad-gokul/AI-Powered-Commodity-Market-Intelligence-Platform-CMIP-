"""API request/response DTOs for extraction runs, entities, and tables."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.modules.extraction.models import EntityType, ExtractionStatus


class ExtractionRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_id: uuid.UUID
    pipeline_version: str
    provider: str
    model: str
    prompt_version: str
    prompt_hash: str
    status: ExtractionStatus
    started_at: datetime | None
    completed_at: datetime | None
    processing_time_ms: int | None
    token_usage: dict[str, Any]
    estimated_cost: float | None
    retry_count: int
    error_message: str | None
    created_at: datetime


class ExtractedEntityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    extraction_run_id: uuid.UUID
    entity_type: EntityType
    raw_value: str
    normalized_value: str | None
    confidence: float
    page_number: int | None
    bounding_box: dict[str, float] | None
    source_chunk: uuid.UUID | None
    provider: str
    model: str
    prompt_version: str
    created_at: datetime


class TableCellRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    row: int
    column: int
    raw_value: str | None
    normalized_value: str | None
    confidence: float


class ExtractedTableRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    extraction_run_id: uuid.UUID
    page_number: int
    title: str | None
    confidence: float
    row_count: int
    column_count: int
    metadata_json: dict[str, Any]
    created_at: datetime


class ExtractedTableDetailRead(ExtractedTableRead):
    cells: list[TableCellRead]
