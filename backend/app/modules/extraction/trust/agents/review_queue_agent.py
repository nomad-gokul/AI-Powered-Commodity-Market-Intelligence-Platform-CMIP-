"""ReviewQueueAgent: decides which entities need a human's attention.
Deterministic, no LLM call - the pipeline's final step, reading every
prior trust-agent's output off context.state (the blackboard pattern
Phase 3.2 established).

Per the spec: confidence below threshold, a validation failure,
conflicting values, or an unresolved canonical entity each queue an
entity for review. One review_queue row per entity (never one per
trigger) - an entity flagged for three reasons gets one row naming all
three, at the highest priority among them, so the queue doesn't fill with
duplicate rows for the same underlying entity.

Known scope boundary: review_queue.entity_id is required by the schema
(see trust/models.py), so a table-level finding (entity_id=None, e.g.
table.inconsistent_totals) is recorded in validation_results for audit
but cannot itself enter the review queue in this phase - a future phase
adding a nullable table_id column would close this gap.
"""

import uuid

from app.ai.engine.types import AgentContext
from app.modules.extraction.trust.agents.schemas import (
    ConfidenceAgentOutput,
    NormalizationAgentOutput,
    ReviewQueueAgentOutput,
    ReviewQueueEntry,
    ValidationAgentOutput,
)
from app.modules.extraction.trust.models import ReviewPriority, ValidationSeverity
from app.modules.extraction.trust.rules.types import ValidationFinding

_LOW_CONFIDENCE_THRESHOLD = 0.6
_CRITICAL_CONFIDENCE_THRESHOLD = 0.4
_CONFLICT_RULE_ID = "entity.conflicting_values"
_PRIORITY_RANK = {
    ReviewPriority.LOW: 0,
    ReviewPriority.MEDIUM: 1,
    ReviewPriority.HIGH: 2,
    ReviewPriority.CRITICAL: 3,
}


class ReviewQueueAgent:
    @property
    def name(self) -> str:
        return "review_queue"

    async def run(self, context: AgentContext) -> ReviewQueueAgentOutput:
        triggers = self._collect_confidence_triggers(context)
        self._add_validation_triggers(context, triggers)
        self._add_normalization_triggers(context, triggers)

        entries = [
            ReviewQueueEntry(
                entity_id=entity_id,
                reason="; ".join(sorted({reason for reason, _ in reasons})),
                priority=max(
                    (priority for _, priority in reasons), key=lambda p: _PRIORITY_RANK[p]
                ),
            )
            for entity_id, reasons in triggers.items()
        ]
        return ReviewQueueAgentOutput(entries=entries)

    def _collect_confidence_triggers(
        self, context: AgentContext
    ) -> dict[uuid.UUID, list[tuple[str, ReviewPriority]]]:
        triggers: dict[uuid.UUID, list[tuple[str, ReviewPriority]]] = {}
        confidence_output = context.state.get("confidence")
        if not isinstance(confidence_output, ConfidenceAgentOutput):
            return triggers
        for score in confidence_output.scores:
            if score.overall_score < _CRITICAL_CONFIDENCE_THRESHOLD:
                triggers.setdefault(score.entity_id, []).append(
                    (
                        f"overall confidence {score.overall_score:.2f} is very low",
                        ReviewPriority.HIGH,
                    )
                )
            elif score.overall_score < _LOW_CONFIDENCE_THRESHOLD:
                triggers.setdefault(score.entity_id, []).append(
                    (
                        f"overall confidence {score.overall_score:.2f} is below threshold",
                        ReviewPriority.MEDIUM,
                    )
                )
        return triggers

    def _add_validation_triggers(
        self,
        context: AgentContext,
        triggers: dict[uuid.UUID, list[tuple[str, ReviewPriority]]],
    ) -> None:
        validation_output = context.state.get("validation")
        if not isinstance(validation_output, ValidationAgentOutput):
            return
        for finding in validation_output.findings:
            if finding.passed or finding.entity_id is None:
                continue
            triggers.setdefault(finding.entity_id, []).append(
                self._priority_for_failed_finding(finding)
            )

    @staticmethod
    def _priority_for_failed_finding(finding: ValidationFinding) -> tuple[str, ReviewPriority]:
        if finding.rule_id == _CONFLICT_RULE_ID:
            return f"conflicting value: {finding.message}", ReviewPriority.HIGH
        message = f"validation failed ({finding.rule_id}): {finding.message}"
        if finding.severity is ValidationSeverity.CRITICAL:
            return message, ReviewPriority.CRITICAL
        if finding.severity is ValidationSeverity.ERROR:
            return message, ReviewPriority.HIGH
        return f"validation warning ({finding.rule_id}): {finding.message}", ReviewPriority.LOW

    def _add_normalization_triggers(
        self,
        context: AgentContext,
        triggers: dict[uuid.UUID, list[tuple[str, ReviewPriority]]],
    ) -> None:
        normalization_output = context.state.get("normalization")
        if not isinstance(normalization_output, NormalizationAgentOutput):
            return
        for outcome in normalization_output.outcomes:
            if outcome.canonical_id is None and outcome.normalization_method == "unresolved":
                triggers.setdefault(outcome.entity_id, []).append(
                    ("unresolved canonical identity", ReviewPriority.LOW)
                )
