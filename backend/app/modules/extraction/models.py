"""ORM models for semantic document extraction (Phase 3.2): one
extraction_run per POST /documents/{id}/extract call, producing
normalized entities and structured tables - not free text.

Rule-light persistence entities, same pattern as app/modules/documents/
models.py: the ORM model doubles as the domain object. The one piece of
real logic this module owns (bounding-box grounding via real PyMuPDF/
pdfplumber coordinates) lives in domain.py, not here.
"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, TimestampMixin


class ExtractionStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class EntityType(StrEnum):
    COMMODITY = "commodity"
    PORT = "port"
    COMPANY = "company"
    COUNTRY = "country"
    CURRENCY = "currency"
    PRICE = "price"
    CONTRACT = "contract"
    DATE = "date"
    QUANTITY = "quantity"
    UNIT = "unit"
    INCOTERM = "incoterm"
    HS_CODE = "hs_code"
    ORGANIZATION = "organization"
    TERMINAL = "terminal"
    VESSEL = "vessel"


def _values(enum_cls: type[StrEnum]) -> Any:
    return lambda e: [m.value for m in e]


_extraction_status_enum = Enum(
    ExtractionStatus, name="extraction_status", values_callable=_values(ExtractionStatus)
)
_entity_type_enum = Enum(EntityType, name="entity_type", values_callable=_values(EntityType))


class ExtractionRun(TimestampMixin, Base):
    __tablename__ = "extraction_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )

    pipeline_version: Mapped[str] = mapped_column(String(32), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    # The primary (DocumentUnderstanding) prompt's version; per-agent
    # versions are recorded individually in metadata_json since each
    # agent's prompt can advance independently.
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False)
    prompt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # sha256(document.sha256_hash + prompt_hash + pipeline_version +
    # provider + model) - see app.modules.extraction.trust.domain.
    # compute_extraction_fingerprint (Phase 3.3). Lets trigger_extraction
    # recognize "this exact extraction already completed" and return the
    # existing run instead of paying for the LLM calls again. Nullable:
    # runs created before Phase 3.3 have none, and simply never match any
    # future fingerprint lookup.
    extraction_fingerprint: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )

    status: Mapped[ExtractionStatus] = mapped_column(
        _extraction_status_enum, nullable=False, default=ExtractionStatus.PENDING
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    processing_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    token_usage: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    estimated_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    retry_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)

    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class ExtractedEntity(TimestampMixin, Base):
    __tablename__ = "extracted_entities"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    extraction_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("extraction_runs.id", ondelete="CASCADE"), nullable=False
    )

    entity_type: Mapped[EntityType] = mapped_column(_entity_type_enum, nullable=False)
    raw_value: Mapped[str] = mapped_column(Text, nullable=False)
    # The LLM's own self-reported normalization for this phase - not
    # independently validated. Real cross-entity normalization
    # (alias resolution, unit conversion) is NormalizationAgent's job,
    # a later phase.
    normalized_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The LLM's own self-reported certainty for this phase - not
    # independently computed/cross-checked. Real confidence scoring
    # (cross-referencing, source agreement) is ConfidenceAgent's job,
    # a later phase.
    confidence: Mapped[float] = mapped_column(Float, nullable=False)

    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # {"x0": float, "y0": float, "x1": float, "y1": float} in PDF points,
    # or null when no confident match was found against the real
    # PyMuPDF word-span geometry - see domain.py's ground_bounding_box().
    bounding_box: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    source_chunk: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_chunks.id", ondelete="SET NULL"), nullable=True
    )

    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False)


class EntityMention(TimestampMixin, Base):
    """A single occurrence of an entity in the source text.

    1:1 with ExtractedEntity in Phase 3.2 (each chunk-level extraction
    produces its own ExtractedEntity row, so it has exactly one mention) -
    the schema supports many mentions per entity so a later phase's
    cross-chunk entity resolution (NormalizationAgent merging "Brent" seen
    in three chunks into one canonical entity) is additive, not a
    migration.
    """

    __tablename__ = "entity_mentions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("extracted_entities.id", ondelete="CASCADE"), nullable=False
    )

    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    character_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)
    surrounding_text: Mapped[str] = mapped_column(Text, nullable=False)
    source_chunk: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_chunks.id", ondelete="SET NULL"), nullable=True
    )


class ExtractedTable(TimestampMixin, Base):
    __tablename__ = "extracted_tables"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    extraction_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("extraction_runs.id", ondelete="CASCADE"), nullable=False
    )

    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    column_count: Mapped[int] = mapped_column(Integer, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class TableCell(TimestampMixin, Base):
    __tablename__ = "table_cells"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    table_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("extracted_tables.id", ondelete="CASCADE"), nullable=False
    )

    row: Mapped[int] = mapped_column(Integer, nullable=False)
    column: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalized_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
