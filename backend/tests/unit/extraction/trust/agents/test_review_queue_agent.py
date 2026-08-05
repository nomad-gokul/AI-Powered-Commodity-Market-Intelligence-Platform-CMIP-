"""Unit tests for ReviewQueueAgent - reads sibling steps' output off
context.state and decides which entities need human review."""

import uuid

import pytest
from shared.agent_contracts import AgentContext

from app.modules.extraction.trust.agents.review_queue_agent import ReviewQueueAgent
from app.modules.extraction.trust.agents.schemas import (
    ConfidenceAgentOutput,
    EntityConfidence,
    NormalizationAgentOutput,
    NormalizationOutcome,
    ValidationAgentOutput,
)
from app.modules.extraction.trust.models import (
    ReviewPriority,
    ValidationCategory,
    ValidationSeverity,
)
from app.modules.extraction.trust.rules.types import ValidationFinding

pytestmark = pytest.mark.asyncio


def _context(**state: object) -> AgentContext:
    context = AgentContext(correlation_id="test")
    context.state.update(state)
    return context


def _confidence(entity_id: uuid.UUID, overall_score: float) -> ConfidenceAgentOutput:
    return ConfidenceAgentOutput(
        scores=[
            EntityConfidence(
                entity_id=entity_id,
                overall_score=overall_score,
                extraction_score=1.0,
                geometry_score=1.0,
                layout_score=1.0,
                table_score=1.0,
                consistency_score=1.0,
                normalization_score=1.0,
                validation_score=1.0,
                provider_score=1.0,
            )
        ]
    )


class TestReviewQueueAgent:
    async def test_name(self) -> None:
        assert ReviewQueueAgent().name == "review_queue"

    async def test_no_prior_output_produces_no_entries(self) -> None:
        output = await ReviewQueueAgent().run(_context())
        assert output.entries == []

    async def test_low_confidence_queues_medium_priority(self) -> None:
        entity_id = uuid.uuid4()
        output = await ReviewQueueAgent().run(_context(confidence=_confidence(entity_id, 0.55)))
        assert len(output.entries) == 1
        assert output.entries[0].priority is ReviewPriority.MEDIUM

    async def test_very_low_confidence_queues_high_priority(self) -> None:
        entity_id = uuid.uuid4()
        output = await ReviewQueueAgent().run(_context(confidence=_confidence(entity_id, 0.1)))
        assert output.entries[0].priority is ReviewPriority.HIGH

    async def test_high_confidence_is_not_queued(self) -> None:
        entity_id = uuid.uuid4()
        output = await ReviewQueueAgent().run(_context(confidence=_confidence(entity_id, 0.95)))
        assert output.entries == []

    async def test_critical_validation_failure_queues_critical_priority(self) -> None:
        entity_id = uuid.uuid4()
        finding = ValidationFinding(
            entity_id=entity_id,
            rule_id="geometry.impossible_bounding_box",
            validation_type=ValidationCategory.GEOMETRY,
            severity=ValidationSeverity.CRITICAL,
            passed=False,
            message="bad geometry",
        )
        output = await ReviewQueueAgent().run(
            _context(validation=ValidationAgentOutput(findings=[finding]))
        )
        assert output.entries[0].priority is ReviewPriority.CRITICAL

    async def test_conflicting_value_queues_high_priority_regardless_of_severity(self) -> None:
        entity_id = uuid.uuid4()
        finding = ValidationFinding(
            entity_id=entity_id,
            rule_id="entity.conflicting_values",
            validation_type=ValidationCategory.CONFLICT,
            severity=ValidationSeverity.WARNING,
            passed=False,
            message="conflict",
        )
        output = await ReviewQueueAgent().run(
            _context(validation=ValidationAgentOutput(findings=[finding]))
        )
        assert output.entries[0].priority is ReviewPriority.HIGH

    async def test_passed_findings_do_not_queue(self) -> None:
        entity_id = uuid.uuid4()
        finding = ValidationFinding(
            entity_id=entity_id,
            rule_id="currency.invalid_code",
            validation_type=ValidationCategory.CURRENCY,
            severity=ValidationSeverity.ERROR,
            passed=True,
            message="ok",
        )
        output = await ReviewQueueAgent().run(
            _context(validation=ValidationAgentOutput(findings=[finding]))
        )
        assert output.entries == []

    async def test_cross_entity_findings_with_no_entity_id_are_ignored(self) -> None:
        finding = ValidationFinding(
            entity_id=None,
            rule_id="table.inconsistent_totals",
            validation_type=ValidationCategory.CONSISTENCY,
            severity=ValidationSeverity.ERROR,
            passed=False,
            message="mismatch",
        )
        output = await ReviewQueueAgent().run(
            _context(validation=ValidationAgentOutput(findings=[finding]))
        )
        assert output.entries == []

    async def test_unresolved_canonical_entity_queues_low_priority(self) -> None:
        entity_id = uuid.uuid4()
        outcome = NormalizationOutcome(
            entity_id=entity_id,
            canonical_id=None,
            canonical_name=None,
            normalized_value=None,
            normalization_method="unresolved",
            confidence=0.0,
        )
        output = await ReviewQueueAgent().run(
            _context(normalization=NormalizationAgentOutput(outcomes=[outcome]))
        )
        assert output.entries[0].priority is ReviewPriority.LOW

    async def test_multiple_triggers_on_the_same_entity_merge_into_one_entry(self) -> None:
        entity_id = uuid.uuid4()
        finding = ValidationFinding(
            entity_id=entity_id,
            rule_id="currency.invalid_code",
            validation_type=ValidationCategory.CURRENCY,
            severity=ValidationSeverity.ERROR,
            passed=False,
            message="bad",
        )
        outcome = NormalizationOutcome(
            entity_id=entity_id,
            canonical_id=None,
            canonical_name=None,
            normalized_value=None,
            normalization_method="unresolved",
            confidence=0.0,
        )
        output = await ReviewQueueAgent().run(
            _context(
                confidence=_confidence(entity_id, 0.5),
                validation=ValidationAgentOutput(findings=[finding]),
                normalization=NormalizationAgentOutput(outcomes=[outcome]),
            )
        )
        assert len(output.entries) == 1
        # Highest priority among the three triggers (HIGH from the
        # validation failure) wins.
        assert output.entries[0].priority is ReviewPriority.HIGH
