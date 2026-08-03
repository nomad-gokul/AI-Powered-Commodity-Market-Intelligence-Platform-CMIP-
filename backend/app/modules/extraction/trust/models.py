"""ORM models for Phase 3.3's trust layer: validation, confidence
scoring, canonical normalization, and the human review queue - all
downstream of Phase 3.2's already-persisted extracted_entities, never a
new extraction of anything.

trust_pipeline_runs is one table beyond the four the spec names
(validation_results, confidence_scores, normalization_results,
review_queue): it is the "run" record this pipeline needs for the same
reason extraction_runs exists for Phase 3.2 - a place to hang
started_at/completed_at/status/error_message/retry_count on, and to let
the same extraction_run be re-validated multiple times (e.g. after a
canonical registry update) with each attempt kept as its own historical
row rather than overwritten in place.

confidence_scores/normalization_results use entity_id as their own
primary key (one row per entity, enforced by the schema itself rather
than an application-level uniqueness check) since the spec's own field
list for those two tables omits a surrogate id - unlike
validation_results/review_queue, which are naturally one-to-many per
entity and get a surrogate UUID id.
"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, TimestampMixin
from app.modules.extraction.models import ExtractionStatus, _values


class ValidationSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class ValidationCategory(StrEnum):
    DATE = "date"
    CURRENCY = "currency"
    QUANTITY = "quantity"
    UNIT = "unit"
    DUPLICATE = "duplicate"
    HS_CODE = "hs_code"
    INCOTERM = "incoterm"
    EXCHANGE_RATE = "exchange_rate"
    GEOMETRY = "geometry"
    CONSISTENCY = "consistency"
    CONFLICT = "conflict"


class ReviewStatus(StrEnum):
    PENDING = "pending"
    IN_REVIEW = "in_review"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class ReviewPriority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


_validation_severity_enum = Enum(
    ValidationSeverity, name="validation_severity", values_callable=_values(ValidationSeverity)
)
_validation_category_enum = Enum(
    ValidationCategory, name="validation_category", values_callable=_values(ValidationCategory)
)
_review_status_enum = Enum(
    ReviewStatus, name="review_status", values_callable=_values(ReviewStatus)
)
_review_priority_enum = Enum(
    ReviewPriority, name="review_priority", values_callable=_values(ReviewPriority)
)
_trust_pipeline_status_enum = Enum(
    ExtractionStatus,
    name="trust_pipeline_status",
    values_callable=_values(ExtractionStatus),
)
"""Reuses ExtractionStatus's Python values (pending/running/completed/failed
means the same thing here) but as its own native Postgres enum type
("trust_pipeline_status", not "extraction_status") - so this table's
migration lifecycle never shares a DB type with extraction_runs and a
downgrade here can never risk that unrelated table."""


class TrustPipelineRun(TimestampMixin, Base):
    __tablename__ = "trust_pipeline_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    extraction_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("extraction_runs.id", ondelete="CASCADE"), nullable=False
    )

    pipeline_version: Mapped[str] = mapped_column(String(32), nullable=False)
    rule_registry_version: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[ExtractionStatus] = mapped_column(
        _trust_pipeline_status_enum, nullable=False, default=ExtractionStatus.PENDING
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    processing_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retry_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    entities_validated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    entities_flagged_for_review: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    average_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)


class ValidationResult(Base):
    __tablename__ = "validation_results"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    extraction_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("extraction_runs.id", ondelete="CASCADE"), nullable=False
    )
    # Nullable: most rules evaluate a single entity, but a handful
    # (duplicate detection, table-total reconciliation) are inherently
    # cross-entity/cross-table - there is no single entity to attribute
    # the finding to, so those rows carry entity_id=None and name the
    # entities/table involved in `message` instead.
    entity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("extracted_entities.id", ondelete="CASCADE"), nullable=True
    )

    validation_rule: Mapped[str] = mapped_column(String(128), nullable=False)
    validation_type: Mapped[ValidationCategory] = mapped_column(
        _validation_category_enum, nullable=False
    )
    severity: Mapped[ValidationSeverity] = mapped_column(_validation_severity_enum, nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp(), nullable=False
    )


class ConfidenceScore(Base):
    __tablename__ = "confidence_scores"

    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("extracted_entities.id", ondelete="CASCADE"),
        primary_key=True,
    )

    overall_score: Mapped[float] = mapped_column(Float, nullable=False)
    extraction_score: Mapped[float] = mapped_column(Float, nullable=False)
    geometry_score: Mapped[float] = mapped_column(Float, nullable=False)
    layout_score: Mapped[float] = mapped_column(Float, nullable=False)
    # table_score/provider_score are additive beyond the spec's literal
    # confidence_scores column list, to satisfy ConfidenceAgent's own
    # named responsibilities ("table", "provider") without dropping
    # either - see docs/ARCHITECTURE.md's Phase 3.3 section.
    table_score: Mapped[float] = mapped_column(Float, nullable=False)
    consistency_score: Mapped[float] = mapped_column(Float, nullable=False)
    normalization_score: Mapped[float] = mapped_column(Float, nullable=False)
    validation_score: Mapped[float] = mapped_column(Float, nullable=False)
    provider_score: Mapped[float] = mapped_column(Float, nullable=False)
    explanation_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp(), nullable=False
    )


class NormalizationResult(Base):
    __tablename__ = "normalization_results"

    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("extracted_entities.id", ondelete="CASCADE"),
        primary_key=True,
    )

    canonical_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    canonical_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    normalized_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalization_method: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp(), nullable=False
    )


class ReviewQueueItem(Base):
    __tablename__ = "review_queue"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Additive beyond the spec's literal field list: lets the API list a
    # run's review items directly instead of joining through entity_id ->
    # extracted_entities.extraction_run_id on every request.
    extraction_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("extraction_runs.id", ondelete="CASCADE"), nullable=False
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("extracted_entities.id", ondelete="CASCADE"), nullable=False
    )

    reason: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[ReviewPriority] = mapped_column(_review_priority_enum, nullable=False)
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[ReviewStatus] = mapped_column(
        _review_status_enum, nullable=False, default=ReviewStatus.PENDING
    )
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp(), nullable=False
    )
