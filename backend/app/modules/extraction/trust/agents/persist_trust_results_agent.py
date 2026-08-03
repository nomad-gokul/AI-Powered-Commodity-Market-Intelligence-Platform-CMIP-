"""PersistTrustResultsAgent: the trust pipeline's final stage, writing
every prior step's in-memory output to Postgres. No LLM call - it's pure
mapping from the four upstream agents' dataclasses to ORM rows.

Delete-then-insert scoped to extraction_run_id (validation_results,
review_queue) or to that run's entity ids (confidence_scores,
normalization_results, which have no extraction_run_id column of their
own - see repository.py) - the same idempotency pattern Phase 3.2
established for ExtractedEntity: re-running this step, whether via an
engine-level retry or an explicit re-trigger of POST
.../validate, replaces rather than duplicates its rows.
"""

import uuid

from app.ai.engine.types import AgentContext
from app.modules.extraction.trust.agents.schemas import (
    ConfidenceAgentOutput,
    NormalizationAgentOutput,
    PersistTrustResultsOutput,
    ReviewQueueAgentOutput,
    ValidationAgentOutput,
)
from app.modules.extraction.trust.models import (
    ConfidenceScore,
    NormalizationResult,
    ReviewQueueItem,
    ValidationResult,
)
from app.modules.extraction.trust.repository import (
    ConfidenceScoreRepository,
    NormalizationResultRepository,
    ReviewQueueRepository,
    ValidationResultRepository,
)


class PersistTrustResultsAgent:
    def __init__(
        self,
        *,
        extraction_run_id: uuid.UUID,
        validation_repo: ValidationResultRepository,
        confidence_repo: ConfidenceScoreRepository,
        normalization_repo: NormalizationResultRepository,
        review_queue_repo: ReviewQueueRepository,
    ) -> None:
        self._extraction_run_id = extraction_run_id
        self._validation_repo = validation_repo
        self._confidence_repo = confidence_repo
        self._normalization_repo = normalization_repo
        self._review_queue_repo = review_queue_repo

    @property
    def name(self) -> str:
        return "persist_trust_results"

    async def run(self, context: AgentContext) -> PersistTrustResultsOutput:
        await self._validation_repo.delete_for_run(self._extraction_run_id)
        await self._confidence_repo.delete_for_run(self._extraction_run_id)
        await self._normalization_repo.delete_for_run(self._extraction_run_id)
        await self._review_queue_repo.delete_for_run(self._extraction_run_id)

        validation_count = await self._persist_validation(context)
        await self._persist_normalization(context)
        average_confidence = await self._persist_confidence(context)
        review_count = await self._persist_review_queue(context)

        return PersistTrustResultsOutput(
            validation_results_persisted=validation_count,
            review_queue_entries_persisted=review_count,
            average_confidence=average_confidence,
        )

    async def _persist_validation(self, context: AgentContext) -> int:
        output = context.state.get("validation")
        if not isinstance(output, ValidationAgentOutput):
            return 0
        rows = [
            ValidationResult(
                extraction_run_id=self._extraction_run_id,
                entity_id=finding.entity_id,
                validation_rule=finding.rule_id,
                validation_type=finding.validation_type,
                severity=finding.severity,
                passed=finding.passed,
                message=finding.message,
            )
            for finding in output.findings
        ]
        created = await self._validation_repo.bulk_create(rows)
        return len(created)

    async def _persist_normalization(self, context: AgentContext) -> None:
        output = context.state.get("normalization")
        if not isinstance(output, NormalizationAgentOutput):
            return
        rows = [
            NormalizationResult(
                entity_id=outcome.entity_id,
                canonical_id=outcome.canonical_id,
                canonical_name=outcome.canonical_name,
                normalized_value=outcome.normalized_value,
                normalization_method=outcome.normalization_method,
                confidence=outcome.confidence,
            )
            for outcome in output.outcomes
        ]
        await self._normalization_repo.bulk_create(rows)

    async def _persist_confidence(self, context: AgentContext) -> float | None:
        output = context.state.get("confidence")
        if not isinstance(output, ConfidenceAgentOutput):
            return None
        rows = [
            ConfidenceScore(
                entity_id=score.entity_id,
                overall_score=score.overall_score,
                extraction_score=score.extraction_score,
                geometry_score=score.geometry_score,
                layout_score=score.layout_score,
                table_score=score.table_score,
                consistency_score=score.consistency_score,
                normalization_score=score.normalization_score,
                validation_score=score.validation_score,
                provider_score=score.provider_score,
                explanation_json=score.explanation,
            )
            for score in output.scores
        ]
        await self._confidence_repo.bulk_create(rows)
        if not rows:
            return None
        return sum(row.overall_score for row in rows) / len(rows)

    async def _persist_review_queue(self, context: AgentContext) -> int:
        output = context.state.get("review_queue")
        if not isinstance(output, ReviewQueueAgentOutput):
            return 0
        rows = [
            ReviewQueueItem(
                extraction_run_id=self._extraction_run_id,
                entity_id=entry.entity_id,
                reason=entry.reason,
                priority=entry.priority,
            )
            for entry in output.entries
        ]
        created = await self._review_queue_repo.bulk_create(rows)
        return len(created)
