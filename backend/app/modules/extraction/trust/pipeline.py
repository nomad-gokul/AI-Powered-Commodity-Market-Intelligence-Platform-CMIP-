"""Builds the SequentialEngine pipeline for one trust-pipeline run:

Validation -> Normalization -> Confidence -> Review Queue -> Persist

This deviates from the spec's own top-to-bottom diagram order (Validation
-> Confidence -> Normalization), which is not internally consistent: the
confidence_scores schema has a normalization_score column, so confidence
scoring must run after normalization produces something to score, not
before. See docs/ARCHITECTURE.md's Phase 3.3 section.

Every step here is deterministic (no LLM call, see agents' own
docstrings), so every step gets the same generous retry policy - unlike
Phase 3.2's extraction pipeline, there is no "one LLM call vs. an
internal loop of many" distinction to make retries expensive or cheap.
"""

import uuid

from shared.agent_contracts import EngineStep, RetryPolicy

from app.modules.extraction.models import ExtractionRun
from app.modules.extraction.repository import (
    ExtractedEntityRepository,
    ExtractedTableRepository,
    TableCellRepository,
)
from app.modules.extraction.trust.agents.confidence_agent import ConfidenceAgent
from app.modules.extraction.trust.agents.normalization_agent import NormalizationAgent
from app.modules.extraction.trust.agents.persist_trust_results_agent import PersistTrustResultsAgent
from app.modules.extraction.trust.agents.review_queue_agent import ReviewQueueAgent
from app.modules.extraction.trust.agents.validation_agent import ValidationAgent
from app.modules.extraction.trust.normalization.loader import CanonicalRegistries
from app.modules.extraction.trust.repository import (
    ConfidenceScoreRepository,
    NormalizationResultRepository,
    ReviewQueueRepository,
    ValidationResultRepository,
)
from app.modules.extraction.trust.rules.registry import ValidationRuleRegistry

_RETRY_POLICY = RetryPolicy(max_attempts=2, backoff_base_seconds=1.0, backoff_multiplier=2.0)
_STEP_TIMEOUT_SECONDS = 120.0


def build_trust_pipeline(
    *,
    extraction_run_id: uuid.UUID,
    extraction_run: ExtractionRun,
    entity_repo: ExtractedEntityRepository,
    table_repo: ExtractedTableRepository,
    cell_repo: TableCellRepository,
    validation_repo: ValidationResultRepository,
    confidence_repo: ConfidenceScoreRepository,
    normalization_repo: NormalizationResultRepository,
    review_queue_repo: ReviewQueueRepository,
    rule_registry: ValidationRuleRegistry,
    canonical_registries: CanonicalRegistries,
) -> list[EngineStep]:
    validation = ValidationAgent(
        extraction_run_id=extraction_run_id,
        entity_repo=entity_repo,
        table_repo=table_repo,
        cell_repo=cell_repo,
        rule_registry=rule_registry,
    )
    normalization = NormalizationAgent(
        extraction_run_id=extraction_run_id,
        entity_repo=entity_repo,
        registries=canonical_registries,
    )
    confidence = ConfidenceAgent(
        extraction_run_id=extraction_run_id,
        extraction_run=extraction_run,
        entity_repo=entity_repo,
        table_repo=table_repo,
    )
    review_queue = ReviewQueueAgent()
    persist = PersistTrustResultsAgent(
        extraction_run_id=extraction_run_id,
        validation_repo=validation_repo,
        confidence_repo=confidence_repo,
        normalization_repo=normalization_repo,
        review_queue_repo=review_queue_repo,
    )

    return [
        EngineStep(agent=agent, retry_policy=_RETRY_POLICY, timeout_seconds=_STEP_TIMEOUT_SECONDS)
        for agent in (validation, normalization, confidence, review_queue, persist)
    ]
