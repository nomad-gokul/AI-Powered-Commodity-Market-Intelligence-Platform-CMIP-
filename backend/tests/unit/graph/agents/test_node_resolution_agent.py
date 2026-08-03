"""Unit tests for NodeResolutionAgent against mocked repositories - pure
computation, never writes to the database."""

import uuid
from unittest.mock import AsyncMock

import pytest

from app.ai.engine.types import AgentContext
from app.modules.extraction.models import EntityType
from app.modules.extraction.trust.models import ConfidenceScore, NormalizationResult
from app.modules.graph.agents.node_resolution_agent import NodeResolutionAgent
from app.modules.graph.models import GraphNode, GraphNodeStatus
from tests.unit.graph.rules._factories import make_entity

pytestmark = pytest.mark.asyncio


def _normalization(entity_id: uuid.UUID, canonical_id: str | None) -> NormalizationResult:
    return NormalizationResult(
        entity_id=entity_id,
        canonical_id=canonical_id,
        canonical_name=canonical_id,
        normalized_value=canonical_id,
        normalization_method="alias_lookup",
        confidence=0.9,
    )


def _confidence(entity_id: uuid.UUID, overall_score: float) -> ConfidenceScore:
    return ConfidenceScore(
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
        explanation_json={},
    )


def _agent(
    *,
    entities: list[object],
    normalization: dict[uuid.UUID, NormalizationResult] | None = None,
    confidence: dict[uuid.UUID, ConfidenceScore] | None = None,
    existing_node: GraphNode | None = None,
) -> NodeResolutionAgent:
    entity_repo = AsyncMock()
    entity_repo.list_all_for_run.return_value = entities
    normalization_repo = AsyncMock()
    normalization_repo.list_for_entities.return_value = normalization or {}
    confidence_repo = AsyncMock()
    confidence_repo.list_for_entities.return_value = confidence or {}
    node_repo = AsyncMock()
    node_repo.get_by_canonical_id.return_value = existing_node
    node_repo.resolve_active_node.side_effect = lambda node: node
    return NodeResolutionAgent(
        extraction_run_id=uuid.uuid4(),
        entity_repo=entity_repo,
        normalization_repo=normalization_repo,
        confidence_repo=confidence_repo,
        node_repo=node_repo,
    )


class TestNodeResolutionAgent:
    async def test_name(self) -> None:
        assert _agent(entities=[]).name == "node_resolution"

    async def test_ineligible_entity_type_is_skipped(self) -> None:
        entity = make_entity(EntityType.CURRENCY, "USD")
        output = await _agent(entities=[entity]).run(AgentContext(correlation_id="test"))
        assert output.entities_skipped_ineligible_type == 1
        assert output.eligible_entities == []

    async def test_unresolved_canonical_id_is_skipped(self) -> None:
        entity = make_entity(EntityType.COMPANY, "Adani Ports")
        output = await _agent(
            entities=[entity], normalization={entity.id: _normalization(entity.id, None)}
        ).run(AgentContext(correlation_id="test"))
        assert output.entities_skipped_unresolved == 1
        assert output.eligible_entities == []

    async def test_missing_confidence_score_is_skipped(self) -> None:
        entity = make_entity(EntityType.COMPANY, "Adani Ports")
        output = await _agent(
            entities=[entity],
            normalization={entity.id: _normalization(entity.id, "company:adani_ports")},
        ).run(AgentContext(correlation_id="test"))
        assert output.entities_skipped_no_confidence == 1
        assert output.eligible_entities == []

    async def test_new_canonical_id_produces_a_new_node_plan(self) -> None:
        entity = make_entity(EntityType.COMPANY, "Adani Ports")
        output = await _agent(
            entities=[entity],
            normalization={entity.id: _normalization(entity.id, "company:adani_ports")},
            confidence={entity.id: _confidence(entity.id, 0.8)},
        ).run(AgentContext(correlation_id="test"))

        assert len(output.node_plans) == 1
        plan = output.node_plans[0]
        assert plan.is_new is True
        assert plan.canonical_id == "company:adani_ports"
        assert plan.new_aliases == frozenset({"Adani Ports"})
        assert len(output.eligible_entities) == 1
        assert output.eligible_entities[0].node_id == plan.node_id
        assert output.eligible_entities[0].overall_confidence == 0.8

    async def test_existing_node_reuses_its_id_and_adds_new_alias(self) -> None:
        entity = make_entity(EntityType.COMPANY, "Adani Ports Ltd")
        existing = GraphNode(
            id=uuid.uuid4(),
            canonical_id="company:adani_ports",
            node_type="company",
            display_name="Adani Ports",
            aliases_json=["Adani Ports"],
            metadata_json={},
            status=GraphNodeStatus.ACTIVE,
            merged_into_id=None,
        )
        output = await _agent(
            entities=[entity],
            normalization={entity.id: _normalization(entity.id, "company:adani_ports")},
            confidence={entity.id: _confidence(entity.id, 0.8)},
            existing_node=existing,
        ).run(AgentContext(correlation_id="test"))

        plan = output.node_plans[0]
        assert plan.is_new is False
        assert plan.node_id == existing.id
        assert plan.new_aliases == frozenset({"Adani Ports Ltd"})

    async def test_existing_alias_is_not_re_added_as_new(self) -> None:
        entity = make_entity(EntityType.COMPANY, "Adani Ports")
        existing = GraphNode(
            id=uuid.uuid4(),
            canonical_id="company:adani_ports",
            node_type="company",
            display_name="Adani Ports",
            aliases_json=["Adani Ports"],
            metadata_json={},
            status=GraphNodeStatus.ACTIVE,
            merged_into_id=None,
        )
        output = await _agent(
            entities=[entity],
            normalization={entity.id: _normalization(entity.id, "company:adani_ports")},
            confidence={entity.id: _confidence(entity.id, 0.8)},
            existing_node=existing,
        ).run(AgentContext(correlation_id="test"))

        assert output.node_plans[0].new_aliases == frozenset()

    async def test_two_entities_sharing_a_canonical_id_produce_one_plan(self) -> None:
        entity_a = make_entity(EntityType.COMPANY, "Adani Ports")
        entity_b = make_entity(EntityType.COMPANY, "Adani Ports Ltd")
        norm = {
            entity_a.id: _normalization(entity_a.id, "company:adani_ports"),
            entity_b.id: _normalization(entity_b.id, "company:adani_ports"),
        }
        conf = {
            entity_a.id: _confidence(entity_a.id, 0.8),
            entity_b.id: _confidence(entity_b.id, 0.7),
        }
        agent = _agent(entities=[entity_a, entity_b], normalization=norm, confidence=conf)
        output = await agent.run(AgentContext(correlation_id="test"))

        assert len(output.node_plans) == 1
        assert output.node_plans[0].new_aliases == frozenset({"Adani Ports", "Adani Ports Ltd"})
        assert len(output.eligible_entities) == 2
        assert output.eligible_entities[0].node_id == output.eligible_entities[1].node_id
