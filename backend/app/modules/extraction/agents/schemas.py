"""Pydantic output models every extraction agent returns.

Every agent returns only these - never free-form text, never a manually
parsed JSON blob. StructuredOutputService validates every LLM response
against one of these before an agent's run() ever sees it (see
app.ai.structured.service). Fields a real, deterministic source can
supply exactly (row_count, column_count, page_number, bounding_box) are
never asked of the LLM - only genuinely interpretive fields are.
"""

import uuid
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

from app.ai.providers.base import LLMUsage
from app.modules.extraction.models import EntityType


class DocumentTypeEnum(StrEnum):
    PRICE_REPORT = "price_report"
    CONTRACT = "contract"
    MARKET_COMMENTARY = "market_commentary"
    SHIPPING_MANIFEST = "shipping_manifest"
    REGULATORY_FILING = "regulatory_filing"
    OTHER = "other"


class DocumentMetadataOutput(BaseModel):
    document_type: DocumentTypeEnum
    commodity: str | None = Field(default=None, description="Primary commodity discussed, if any")
    language: str | None = Field(default=None, description="ISO 639-1 code, e.g. 'en'")
    business_domain: str = Field(description="e.g. 'crude oil freight', 'grain trading'")
    extraction_strategy: str = Field(
        description=(
            "Short guidance for downstream extraction agents, e.g. "
            "'focus on the daily price assessment table on page 2'"
        )
    )
    confidence: float = Field(ge=0.0, le=1.0)


class ReadingOrderBlock(BaseModel):
    block_index: int
    role: Literal["header", "footer", "title", "body", "table_caption", "other"]


class PageLayout(BaseModel):
    page_number: int
    is_multi_column: bool
    column_count: int
    reading_order: list[ReadingOrderBlock]
    notes: str | None = None


class LayoutModel(BaseModel):
    pages: list[PageLayout]


class ExtractedEntityItem(BaseModel):
    entity_type: EntityType
    raw_value: str = Field(description="The exact text as it appears in the source")
    normalized_value: str | None = Field(
        default=None, description="Your best-effort normalization, e.g. 'USD' for '$'"
    )
    confidence: float = Field(ge=0.0, le=1.0)


class EntityExtractionOutput(BaseModel):
    entities: list[ExtractedEntityItem]


class TableCellItem(BaseModel):
    row: int = Field(ge=0, description="0-indexed row within the table")
    column: int = Field(ge=0, description="0-indexed column within the table")
    normalized_value: str | None = Field(
        default=None, description="Your best-effort normalization of this cell's value"
    )
    confidence: float = Field(ge=0.0, le=1.0)


class TableExtractionOutput(BaseModel):
    title: str | None = Field(default=None, description="A short caption/title for this table")
    confidence: float = Field(ge=0.0, le=1.0)
    cells: list[TableCellItem]


# --- Agent return types --------------------------------------------------
#
# What each agent's run() actually returns: the raw LLM response schemas
# above, enriched with real (never LLM-provided) grounding data - page
# numbers, bounding boxes, chunk/table structure - and per-agent token
# usage for observability. Still Pydantic models throughout, per this
# phase's "every agent returns only Pydantic models" requirement.


class DocumentUnderstandingAgentOutput(BaseModel):
    metadata: DocumentMetadataOutput
    total_usage: LLMUsage = Field(default_factory=LLMUsage)


class BoundingBoxModel(BaseModel):
    x0: float
    y0: float
    x1: float
    y1: float


class PageSpanModel(BaseModel):
    page_number: int
    text: str
    bbox: BoundingBoxModel


class LayoutAgentOutput(BaseModel):
    layout: LayoutModel
    spans: list[PageSpanModel]
    total_usage: LLMUsage = Field(default_factory=LLMUsage)


class GroundedEntity(BaseModel):
    entity_type: EntityType
    raw_value: str
    normalized_value: str | None
    confidence: float
    page_number: int | None
    bounding_box: BoundingBoxModel | None
    source_chunk_id: uuid.UUID | None


class EntityExtractionAgentOutput(BaseModel):
    entities: list[GroundedEntity]
    total_usage: LLMUsage = Field(default_factory=LLMUsage)


class GroundedCell(BaseModel):
    row: int
    column: int
    raw_value: str | None
    normalized_value: str | None
    confidence: float
    bounding_box: BoundingBoxModel | None


class GroundedTable(BaseModel):
    page_number: int
    title: str | None
    confidence: float
    row_count: int
    column_count: int
    bounding_box: BoundingBoxModel | None
    cells: list[GroundedCell]


class TableExtractionAgentOutput(BaseModel):
    tables: list[GroundedTable]
    total_usage: LLMUsage = Field(default_factory=LLMUsage)


class PersistResultsOutput(BaseModel):
    extraction_run_id: uuid.UUID
    entities_persisted: int
    tables_persisted: int
    cells_persisted: int
