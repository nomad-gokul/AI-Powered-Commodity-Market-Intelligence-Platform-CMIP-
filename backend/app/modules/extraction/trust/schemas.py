"""API request/response DTOs for the trust layer."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.modules.extraction.models import ExtractionStatus
from app.modules.extraction.trust.models import (
    ReviewPriority,
    ReviewStatus,
    ValidationCategory,
    ValidationSeverity,
)


class TrustPipelineRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    extraction_run_id: uuid.UUID
    pipeline_version: str
    rule_registry_version: str
    status: ExtractionStatus
    started_at: datetime | None
    completed_at: datetime | None
    processing_time_ms: int | None
    retry_count: int
    error_message: str | None
    entities_validated: int
    entities_flagged_for_review: int
    average_confidence: float | None
    created_at: datetime


class ValidationResultRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    extraction_run_id: uuid.UUID
    entity_id: uuid.UUID | None
    validation_rule: str
    validation_type: ValidationCategory
    severity: ValidationSeverity
    passed: bool
    message: str
    created_at: datetime


class ConfidenceScoreRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    entity_id: uuid.UUID
    overall_score: float
    extraction_score: float
    geometry_score: float
    layout_score: float
    table_score: float
    consistency_score: float
    normalization_score: float
    validation_score: float
    provider_score: float
    explanation_json: dict[str, Any]
    created_at: datetime


class NormalizationResultRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    entity_id: uuid.UUID
    canonical_id: str | None
    canonical_name: str | None
    normalized_value: str | None
    normalization_method: str
    confidence: float
    created_at: datetime


class ReviewQueueItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    extraction_run_id: uuid.UUID
    entity_id: uuid.UUID
    reason: str
    priority: ReviewPriority
    assigned_to: uuid.UUID | None
    status: ReviewStatus
    resolution: str | None
    reviewed_at: datetime | None
    created_at: datetime


class ReviewQueueUpdateRequest(BaseModel):
    status: ReviewStatus | None = None
    assigned_to: uuid.UUID | None = None
    resolution: str | None = None
