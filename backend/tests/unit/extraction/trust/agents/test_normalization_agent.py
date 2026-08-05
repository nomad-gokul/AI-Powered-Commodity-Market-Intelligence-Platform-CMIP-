"""Unit tests for NormalizationAgent against mocked repositories."""

import uuid
from unittest.mock import AsyncMock

import pytest
from shared.agent_contracts import AgentContext

from app.modules.extraction.models import EntityType
from app.modules.extraction.trust.agents.normalization_agent import NormalizationAgent
from app.modules.extraction.trust.normalization.loader import get_canonical_registries
from tests.unit.extraction.trust.rules._factories import make_entity

pytestmark = pytest.mark.asyncio


def _agent(entities: list[object]) -> NormalizationAgent:
    entity_repo = AsyncMock()
    entity_repo.list_all_for_run.return_value = entities
    return NormalizationAgent(
        extraction_run_id=uuid.uuid4(),
        entity_repo=entity_repo,
        registries=get_canonical_registries(),
    )


class TestNormalizationAgent:
    async def test_name(self) -> None:
        assert _agent([]).name == "normalization"

    async def test_closed_set_alias_lookup(self) -> None:
        entity = make_entity(entity_type=EntityType.COUNTRY, raw_value="USA")
        output = await _agent([entity]).run(AgentContext(correlation_id="test"))
        outcome = output.outcomes[0]
        assert outcome.canonical_id == "country:US"
        assert outcome.normalization_method == "alias_lookup"
        assert outcome.confidence == 1.0

    async def test_closed_set_unresolved(self) -> None:
        entity = make_entity(entity_type=EntityType.CURRENCY, raw_value="NOT_REAL")
        output = await _agent([entity]).run(AgentContext(correlation_id="test"))
        outcome = output.outcomes[0]
        assert outcome.canonical_id is None
        assert outcome.normalization_method == "unresolved"
        assert outcome.confidence == 0.0

    async def test_commodity_falls_back_to_slug_when_alias_misses(self) -> None:
        entity = make_entity(entity_type=EntityType.COMMODITY, raw_value="Some Obscure Grade XZ")
        output = await _agent([entity]).run(AgentContext(correlation_id="test"))
        outcome = output.outcomes[0]
        assert outcome.canonical_id == "commodity:some_obscure_grade_xz"
        assert outcome.normalization_method == "slug_derived_fallback"

    async def test_commodity_alias_hit_takes_precedence_over_slug(self) -> None:
        entity = make_entity(entity_type=EntityType.COMMODITY, raw_value="Brent")
        output = await _agent([entity]).run(AgentContext(correlation_id="test"))
        outcome = output.outcomes[0]
        assert outcome.canonical_id == "commodity:brent_crude"
        assert outcome.normalization_method == "alias_lookup"

    async def test_company_is_always_slug_derived(self) -> None:
        entity = make_entity(entity_type=EntityType.COMPANY, raw_value="Adani Ports & SEZ Ltd")
        output = await _agent([entity]).run(AgentContext(correlation_id="test"))
        outcome = output.outcomes[0]
        assert outcome.canonical_id == "company:adani_ports_sez"
        assert outcome.normalization_method == "slug_derived"

    async def test_hs_code_resolves_via_chapter_prefix(self) -> None:
        entity = make_entity(entity_type=EntityType.HS_CODE, raw_value="27101943")
        output = await _agent([entity]).run(AgentContext(correlation_id="test"))
        outcome = output.outcomes[0]
        assert outcome.canonical_id == "hs:27"
        assert outcome.normalization_method == "prefix_lookup"

    async def test_hs_code_with_unlisted_chapter_still_format_normalizes(self) -> None:
        entity = make_entity(entity_type=EntityType.HS_CODE, raw_value="99101943")
        output = await _agent([entity]).run(AgentContext(correlation_id="test"))
        outcome = output.outcomes[0]
        assert outcome.canonical_id == "hs:99"
        assert outcome.normalization_method == "format_normalized"

    async def test_contract_is_literal_normalized(self) -> None:
        entity = make_entity(entity_type=EntityType.CONTRACT, raw_value="  ct-2026/001  ")
        output = await _agent([entity]).run(AgentContext(correlation_id="test"))
        outcome = output.outcomes[0]
        assert outcome.canonical_id == "contract:CT-2026/001"
        assert outcome.normalization_method == "literal_normalized"

    async def test_date_normalizes_to_iso(self) -> None:
        entity = make_entity(entity_type=EntityType.DATE, raw_value="12 January 2026")
        output = await _agent([entity]).run(AgentContext(correlation_id="test"))
        outcome = output.outcomes[0]
        assert outcome.canonical_id is None
        assert outcome.normalized_value == "2026-01-12"
        assert outcome.normalization_method == "value_parsed"

    async def test_unparseable_date_is_unresolved(self) -> None:
        entity = make_entity(entity_type=EntityType.DATE, raw_value="whenever")
        output = await _agent([entity]).run(AgentContext(correlation_id="test"))
        assert output.outcomes[0].normalization_method == "unresolved"

    async def test_quantity_resolves_embedded_unit(self) -> None:
        entity = make_entity(entity_type=EntityType.QUANTITY, raw_value="500 MT")
        output = await _agent([entity]).run(AgentContext(correlation_id="test"))
        outcome = output.outcomes[0]
        assert outcome.normalized_value == "500.0 unit:metric_ton"
        assert outcome.confidence == 0.9

    async def test_quantity_without_recognizable_unit_still_parses_value(self) -> None:
        entity = make_entity(entity_type=EntityType.QUANTITY, raw_value="500 xyzzy")
        output = await _agent([entity]).run(AgentContext(correlation_id="test"))
        outcome = output.outcomes[0]
        assert outcome.normalized_value == "500.0"
        assert outcome.confidence == 0.6

    async def test_price_resolves_embedded_currency(self) -> None:
        entity = make_entity(entity_type=EntityType.PRICE, raw_value="$82.14 per barrel")
        output = await _agent([entity]).run(AgentContext(correlation_id="test"))
        outcome = output.outcomes[0]
        assert "currency:USD" in outcome.normalized_value
        assert outcome.confidence == 0.9
