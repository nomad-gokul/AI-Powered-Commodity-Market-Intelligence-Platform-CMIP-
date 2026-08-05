"""Unit tests for ValidationAgent against mocked repositories."""

import uuid
from unittest.mock import AsyncMock

import pytest
from shared.agent_contracts import AgentContext

from app.modules.extraction.models import EntityType
from app.modules.extraction.trust.agents.schemas import ValidationAgentOutput
from app.modules.extraction.trust.agents.validation_agent import ValidationAgent
from app.modules.extraction.trust.rules.builtin import get_validation_rule_registry
from tests.unit.extraction.trust.rules._factories import make_entity

pytestmark = pytest.mark.asyncio


def _agent(*, entities: list[object], tables: list[object] | None = None) -> ValidationAgent:
    entity_repo = AsyncMock()
    entity_repo.list_all_for_run.return_value = entities
    table_repo = AsyncMock()
    table_repo.list_for_run.return_value = tables or []
    cell_repo = AsyncMock()
    cell_repo.list_for_tables.return_value = {}
    return ValidationAgent(
        extraction_run_id=uuid.uuid4(),
        entity_repo=entity_repo,
        table_repo=table_repo,
        cell_repo=cell_repo,
        rule_registry=get_validation_rule_registry(),
    )


class TestValidationAgent:
    async def test_name(self) -> None:
        assert _agent(entities=[]).name == "validation"

    async def test_runs_applicable_entity_rules(self) -> None:
        entity = make_entity(entity_type=EntityType.CURRENCY, raw_value="USD")
        agent = _agent(entities=[entity])
        output = await agent.run(AgentContext(correlation_id="test"))
        assert isinstance(output, ValidationAgentOutput)
        assert any(f.entity_id == entity.id for f in output.findings)

    async def test_no_entities_still_runs_cross_entity_rules_without_error(self) -> None:
        agent = _agent(entities=[])
        output = await agent.run(AgentContext(correlation_id="test"))
        assert output.findings == []

    async def test_duplicate_entities_are_flagged(self) -> None:
        first = make_entity(entity_type=EntityType.COMMODITY, raw_value="Brent", page_number=1)
        second = make_entity(entity_type=EntityType.COMMODITY, raw_value="Brent", page_number=1)
        agent = _agent(entities=[first, second])
        output = await agent.run(AgentContext(correlation_id="test"))
        duplicate_findings = [f for f in output.findings if f.rule_id == "entity.duplicate"]
        assert len(duplicate_findings) == 1

    async def test_invalid_currency_produces_a_failed_finding(self) -> None:
        entity = make_entity(entity_type=EntityType.CURRENCY, raw_value="NOT_A_CURRENCY")
        agent = _agent(entities=[entity])
        output = await agent.run(AgentContext(correlation_id="test"))
        failed = [f for f in output.findings if not f.passed]
        assert any(f.rule_id == "currency.invalid_code" for f in failed)
