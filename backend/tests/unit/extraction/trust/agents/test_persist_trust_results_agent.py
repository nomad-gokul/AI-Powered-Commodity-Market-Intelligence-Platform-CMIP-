"""Unit tests for PersistTrustResultsAgent against mocked repositories -
real-database persistence correctness is covered by the integration
suite; this tests the agent's own ORM-row-building and idempotency call
sequence."""

import uuid
from unittest.mock import AsyncMock

import pytest

from app.ai.engine.types import AgentContext
from app.modules.extraction.trust.agents.persist_trust_results_agent import (
    PersistTrustResultsAgent,
)
from app.modules.extraction.trust.agents.schemas import (
    ConfidenceAgentOutput,
    EntityConfidence,
    NormalizationAgentOutput,
    NormalizationOutcome,
    ReviewQueueAgentOutput,
    ReviewQueueEntry,
    ValidationAgentOutput,
)
from app.modules.extraction.trust.models import (
    ReviewPriority,
    ValidationCategory,
    ValidationSeverity,
)
from app.modules.extraction.trust.rules.types import ValidationFinding

pytestmark = pytest.mark.asyncio

Repos = dict[str, AsyncMock]


def _context(**state: object) -> AgentContext:
    context = AgentContext(correlation_id="test")
    context.state.update(state)
    return context


@pytest.fixture
def repos() -> Repos:
    validation_repo = AsyncMock()
    validation_repo.bulk_create.side_effect = lambda rows: rows
    confidence_repo = AsyncMock()
    confidence_repo.bulk_create.side_effect = lambda rows: rows
    normalization_repo = AsyncMock()
    normalization_repo.bulk_create.side_effect = lambda rows: rows
    review_queue_repo = AsyncMock()
    review_queue_repo.bulk_create.side_effect = lambda rows: rows
    return {
        "validation_repo": validation_repo,
        "confidence_repo": confidence_repo,
        "normalization_repo": normalization_repo,
        "review_queue_repo": review_queue_repo,
    }


def _agent(repos: Repos) -> PersistTrustResultsAgent:
    return PersistTrustResultsAgent(
        extraction_run_id=uuid.uuid4(),
        validation_repo=repos["validation_repo"],
        confidence_repo=repos["confidence_repo"],
        normalization_repo=repos["normalization_repo"],
        review_queue_repo=repos["review_queue_repo"],
    )


class TestPersistTrustResultsAgent:
    async def test_name(self, repos: Repos) -> None:
        assert _agent(repos).name == "persist_trust_results"

    async def test_deletes_before_inserting_for_idempotency(self, repos: Repos) -> None:
        await _agent(repos).run(_context())
        repos["validation_repo"].delete_for_run.assert_awaited_once()
        repos["confidence_repo"].delete_for_run.assert_awaited_once()
        repos["normalization_repo"].delete_for_run.assert_awaited_once()
        repos["review_queue_repo"].delete_for_run.assert_awaited_once()

    async def test_persists_validation_findings(self, repos: Repos) -> None:
        finding = ValidationFinding(
            entity_id=uuid.uuid4(),
            rule_id="currency.invalid_code",
            validation_type=ValidationCategory.CURRENCY,
            severity=ValidationSeverity.ERROR,
            passed=False,
            message="bad",
        )
        output = await _agent(repos).run(
            _context(validation=ValidationAgentOutput(findings=[finding]))
        )
        repos["validation_repo"].bulk_create.assert_awaited_once()
        assert output.validation_results_persisted == 1

    async def test_persists_confidence_scores_and_returns_average(self, repos: Repos) -> None:
        score = EntityConfidence(
            entity_id=uuid.uuid4(),
            overall_score=0.8,
            extraction_score=1.0,
            geometry_score=1.0,
            layout_score=1.0,
            table_score=1.0,
            consistency_score=1.0,
            normalization_score=1.0,
            validation_score=1.0,
            provider_score=1.0,
        )
        another = EntityConfidence(
            entity_id=uuid.uuid4(),
            overall_score=0.4,
            extraction_score=1.0,
            geometry_score=1.0,
            layout_score=1.0,
            table_score=1.0,
            consistency_score=1.0,
            normalization_score=1.0,
            validation_score=1.0,
            provider_score=1.0,
        )
        output = await _agent(repos).run(
            _context(confidence=ConfidenceAgentOutput(scores=[score, another]))
        )
        repos["confidence_repo"].bulk_create.assert_awaited_once()
        assert output.average_confidence == pytest.approx(0.6)

    async def test_no_confidence_output_returns_none_average(self, repos: Repos) -> None:
        output = await _agent(repos).run(_context())
        assert output.average_confidence is None

    async def test_persists_normalization_outcomes(self, repos: Repos) -> None:
        outcome = NormalizationOutcome(
            entity_id=uuid.uuid4(),
            canonical_id="country:US",
            canonical_name="United States",
            normalized_value="United States",
            normalization_method="alias_lookup",
            confidence=1.0,
        )
        await _agent(repos).run(
            _context(normalization=NormalizationAgentOutput(outcomes=[outcome]))
        )
        repos["normalization_repo"].bulk_create.assert_awaited_once()

    async def test_persists_review_queue_entries(self, repos: Repos) -> None:
        entry = ReviewQueueEntry(
            entity_id=uuid.uuid4(), reason="low confidence", priority=ReviewPriority.MEDIUM
        )
        output = await _agent(repos).run(
            _context(review_queue=ReviewQueueAgentOutput(entries=[entry]))
        )
        repos["review_queue_repo"].bulk_create.assert_awaited_once()
        assert output.review_queue_entries_persisted == 1

    async def test_missing_step_output_is_a_no_op_not_an_error(self, repos: Repos) -> None:
        output = await _agent(repos).run(_context())
        assert output.validation_results_persisted == 0
        assert output.review_queue_entries_persisted == 0
