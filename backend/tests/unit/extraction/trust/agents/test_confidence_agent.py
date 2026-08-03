"""Unit tests for ConfidenceAgent against mocked repositories."""

import uuid
from unittest.mock import AsyncMock

import pytest

from app.ai.engine.types import AgentContext
from app.modules.extraction.models import EntityType, ExtractionRun, ExtractionStatus
from app.modules.extraction.trust.agents.confidence_agent import ConfidenceAgent
from app.modules.extraction.trust.agents.schemas import (
    NormalizationAgentOutput,
    NormalizationOutcome,
    ValidationAgentOutput,
)
from app.modules.extraction.trust.models import ValidationCategory, ValidationSeverity
from app.modules.extraction.trust.rules.types import ValidationFinding
from tests.unit.extraction.trust.rules._factories import make_entity, make_table

pytestmark = pytest.mark.asyncio


def _run(
    *, provider: str = "groq", metadata_json: dict[str, object] | None = None
) -> ExtractionRun:
    return ExtractionRun(
        id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        pipeline_version="3.2.0",
        provider=provider,
        model="test-model",
        prompt_version="1.0",
        prompt_hash="hash",
        status=ExtractionStatus.COMPLETED,
        metadata_json=metadata_json or {},
    )


def _context(**state: object) -> AgentContext:
    context = AgentContext(correlation_id="test")
    context.state.update(state)
    return context


def _agent(
    *,
    entities: list[object],
    tables: list[object] | None = None,
    extraction_run: ExtractionRun | None = None,
) -> ConfidenceAgent:
    run = extraction_run or _run()
    entity_repo = AsyncMock()
    entity_repo.list_all_for_run.return_value = entities
    table_repo = AsyncMock()
    table_repo.list_for_run.return_value = tables or []
    return ConfidenceAgent(
        extraction_run_id=run.id,
        extraction_run=run,
        entity_repo=entity_repo,
        table_repo=table_repo,
    )


class TestConfidenceAgent:
    async def test_name(self) -> None:
        assert _agent(entities=[]).name == "confidence"

    async def test_extraction_score_reflects_entity_confidence(self) -> None:
        entity = make_entity(entity_type=EntityType.COMMODITY, raw_value="Brent", confidence=0.42)
        output = await _agent(entities=[entity]).run(_context())
        assert output.scores[0].extraction_score == 0.42

    async def test_grounded_entity_gets_full_geometry_score(self) -> None:
        entity = make_entity(
            entity_type=EntityType.COMMODITY,
            raw_value="Brent",
            bounding_box={"x0": 1.0, "y0": 1.0, "x1": 10.0, "y1": 10.0},
        )
        output = await _agent(entities=[entity]).run(_context())
        assert output.scores[0].geometry_score == 1.0

    async def test_ungrounded_entity_gets_penalized_geometry_score(self) -> None:
        entity = make_entity(entity_type=EntityType.COMMODITY, raw_value="Brent", bounding_box=None)
        output = await _agent(entities=[entity]).run(_context())
        assert output.scores[0].geometry_score < 1.0

    async def test_layout_score_reads_run_metadata(self) -> None:
        entity = make_entity(entity_type=EntityType.COMMODITY, raw_value="Brent", page_number=1)
        run = _run(metadata_json={"layout_summary": {"1": {"is_multi_column": True}}})
        output = await _agent(entities=[entity], extraction_run=run).run(_context())
        assert output.scores[0].layout_score < 1.0

    async def test_table_score_averages_confidence_of_tables_on_same_page(self) -> None:
        entity = make_entity(entity_type=EntityType.COMMODITY, raw_value="Brent", page_number=1)
        table = make_table(page_number=1, confidence=0.5)
        output = await _agent(entities=[entity], tables=[table]).run(_context())
        assert output.scores[0].table_score == 0.5

    async def test_validation_score_reflects_passed_findings_for_entity(self) -> None:
        entity = make_entity(entity_type=EntityType.CURRENCY, raw_value="USD")
        finding = ValidationFinding(
            entity_id=entity.id,
            rule_id="currency.invalid_code",
            validation_type=ValidationCategory.CURRENCY,
            severity=ValidationSeverity.ERROR,
            passed=True,
            message="ok",
        )
        output = await _agent(entities=[entity]).run(
            _context(validation=ValidationAgentOutput(findings=[finding]))
        )
        assert output.scores[0].validation_score == 1.0

    async def test_validation_score_drops_on_failed_finding(self) -> None:
        entity = make_entity(entity_type=EntityType.CURRENCY, raw_value="ZZZ")
        finding = ValidationFinding(
            entity_id=entity.id,
            rule_id="currency.invalid_code",
            validation_type=ValidationCategory.CURRENCY,
            severity=ValidationSeverity.ERROR,
            passed=False,
            message="bad",
        )
        output = await _agent(entities=[entity]).run(
            _context(validation=ValidationAgentOutput(findings=[finding]))
        )
        assert output.scores[0].validation_score == 0.0

    async def test_consistency_score_is_separate_from_validation_score(self) -> None:
        entity = make_entity(entity_type=EntityType.COMMODITY, raw_value="Brent")
        duplicate_finding = ValidationFinding(
            entity_id=entity.id,
            rule_id="entity.duplicate",
            validation_type=ValidationCategory.DUPLICATE,
            severity=ValidationSeverity.WARNING,
            passed=False,
            message="dup",
        )
        output = await _agent(entities=[entity]).run(
            _context(validation=ValidationAgentOutput(findings=[duplicate_finding]))
        )
        score = output.scores[0]
        assert score.consistency_score == 0.0
        assert score.validation_score == 1.0  # unaffected - no non-consistency findings

    async def test_normalization_score_reads_sibling_step_output(self) -> None:
        entity = make_entity(entity_type=EntityType.COUNTRY, raw_value="USA")
        outcome = NormalizationOutcome(
            entity_id=entity.id,
            canonical_id="country:US",
            canonical_name="United States",
            normalized_value="United States",
            normalization_method="alias_lookup",
            confidence=1.0,
        )
        output = await _agent(entities=[entity]).run(
            _context(normalization=NormalizationAgentOutput(outcomes=[outcome]))
        )
        assert output.scores[0].normalization_score == 1.0

    async def test_provider_score_uses_known_provider_reliability(self) -> None:
        entity = make_entity(entity_type=EntityType.COMMODITY, raw_value="Brent")
        run = _run(provider="claude")
        output = await _agent(entities=[entity], extraction_run=run).run(_context())
        assert output.scores[0].provider_score == 0.95

    async def test_provider_score_defaults_for_unknown_provider(self) -> None:
        entity = make_entity(entity_type=EntityType.COMMODITY, raw_value="Brent")
        run = _run(provider="some_new_vendor")
        output = await _agent(entities=[entity], extraction_run=run).run(_context())
        assert output.scores[0].provider_score == 0.8

    async def test_overall_score_is_within_unit_interval(self) -> None:
        entity = make_entity(entity_type=EntityType.COMMODITY, raw_value="Brent", confidence=0.9)
        output = await _agent(entities=[entity]).run(_context())
        assert 0.0 <= output.scores[0].overall_score <= 1.0

    async def test_explanation_includes_every_dimension(self) -> None:
        entity = make_entity(entity_type=EntityType.COMMODITY, raw_value="Brent")
        output = await _agent(entities=[entity]).run(_context())
        components = output.scores[0].explanation["components"]
        for dimension in (
            "extraction",
            "geometry",
            "layout",
            "table",
            "validation",
            "consistency",
            "normalization",
            "provider",
        ):
            assert dimension in components
