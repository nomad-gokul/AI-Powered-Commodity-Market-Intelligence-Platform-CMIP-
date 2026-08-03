"""Output types every trust-layer agent returns via context.state.

None of these are Pydantic models with LLM-validated schemas, unlike
Phase 3.2's agent outputs - these four agents make no LLM call at all
(see docs/ARCHITECTURE.md's Phase 3.3 section for why), so there is no
untrusted model response to validate against a schema. Plain frozen
dataclasses are the right weight here: internal, deterministic, never
serialized directly to an API response (PersistTrustResultsAgent maps
them to ORM rows; schemas.py in this package's parent maps ORM rows to
API DTOs).
"""

import uuid
from dataclasses import dataclass, field
from typing import Any

from app.modules.extraction.trust.models import ReviewPriority
from app.modules.extraction.trust.rules.types import ValidationFinding


@dataclass(frozen=True, slots=True)
class ValidationAgentOutput:
    findings: list[ValidationFinding]


@dataclass(frozen=True, slots=True)
class NormalizationOutcome:
    entity_id: uuid.UUID
    canonical_id: str | None
    canonical_name: str | None
    normalized_value: str | None
    normalization_method: str
    confidence: float


@dataclass(frozen=True, slots=True)
class NormalizationAgentOutput:
    outcomes: list[NormalizationOutcome]


@dataclass(frozen=True, slots=True)
class EntityConfidence:
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
    explanation: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ConfidenceAgentOutput:
    scores: list[EntityConfidence]


@dataclass(frozen=True, slots=True)
class ReviewQueueEntry:
    entity_id: uuid.UUID
    reason: str
    priority: ReviewPriority


@dataclass(frozen=True, slots=True)
class ReviewQueueAgentOutput:
    entries: list[ReviewQueueEntry]


@dataclass(frozen=True, slots=True)
class PersistTrustResultsOutput:
    validation_results_persisted: int
    review_queue_entries_persisted: int
    average_confidence: float | None
