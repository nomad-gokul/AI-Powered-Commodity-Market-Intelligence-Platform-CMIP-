"""Unit tests for RelationshipExtractionAgent against mocked
repositories - reads NodeResolutionAgent's output off the blackboard,
never writes to the database."""

import uuid
from unittest.mock import AsyncMock

import pytest

from app.ai.engine.types import AgentContext
from app.modules.documents.models import DocumentChunk
from app.modules.extraction.models import EntityMention, EntityType, ExtractionRun, ExtractionStatus
from app.modules.graph.agents.relationship_extraction_agent import RelationshipExtractionAgent
from app.modules.graph.agents.schemas import EligibleEntity, NodeResolutionOutput
from app.modules.graph.domain import MIN_EDGE_CONFIDENCE
from app.modules.graph.rules.builtin import get_relationship_rule_registry
from tests.unit.graph.rules._factories import make_entity, make_mention

pytestmark = pytest.mark.asyncio


def _chunk(chunk_id: uuid.UUID, text: str) -> DocumentChunk:
    return DocumentChunk(
        id=chunk_id,
        document_id=uuid.uuid4(),
        chunk_index=0,
        page_number=1,
        text=text,
        token_count=10,
        metadata_json={},
    )


def _extraction_run(run_id: uuid.UUID) -> ExtractionRun:
    return ExtractionRun(
        id=run_id,
        document_id=uuid.uuid4(),
        pipeline_version="3.2.0",
        provider="groq",
        model="test-model",
        prompt_version="1.0",
        prompt_hash="a" * 64,
        status=ExtractionStatus.COMPLETED,
    )


def _agent(
    *,
    extraction_run_id: uuid.UUID,
    mentions: dict[uuid.UUID, list[EntityMention]],
    chunks: dict[uuid.UUID, DocumentChunk],
    extraction_run: ExtractionRun,
) -> RelationshipExtractionAgent:
    mention_repo = AsyncMock()
    mention_repo.list_for_entities.return_value = mentions
    chunk_repo = AsyncMock()
    chunk_repo.list_by_ids.return_value = chunks
    extraction_run_repo = AsyncMock()
    extraction_run_repo.get_by_id.return_value = extraction_run
    return RelationshipExtractionAgent(
        extraction_run_id=extraction_run_id,
        mention_repo=mention_repo,
        chunk_repo=chunk_repo,
        extraction_run_repo=extraction_run_repo,
        rule_registry=get_relationship_rule_registry(),
    )


def _eligible(
    entity: object, node_id: uuid.UUID, canonical_id: str, confidence: float = 1.0
) -> EligibleEntity:
    return EligibleEntity(
        entity=entity,  # type: ignore[arg-type]
        node_id=node_id,
        canonical_id=canonical_id,
        overall_confidence=confidence,
    )


class TestRelationshipExtractionAgent:
    async def test_name(self) -> None:
        run_id = uuid.uuid4()
        agent = _agent(
            extraction_run_id=run_id, mentions={}, chunks={}, extraction_run=_extraction_run(run_id)
        )
        assert agent.name == "relationship_extraction"

    async def test_no_eligible_entities_produces_no_findings(self) -> None:
        run_id = uuid.uuid4()
        agent = _agent(
            extraction_run_id=run_id, mentions={}, chunks={}, extraction_run=_extraction_run(run_id)
        )
        context = AgentContext(correlation_id="test")
        context.state["node_resolution"] = NodeResolutionOutput(
            node_plans=[],
            eligible_entities=[],
            entities_skipped_ineligible_type=0,
            entities_skipped_unresolved=0,
            entities_skipped_no_confidence=0,
        )

        output = await agent.run(context)

        assert output.findings == []
        assert output.candidate_pairs_evaluated == 0

    async def test_same_chunk_pattern_match_produces_a_finding(self) -> None:
        run_id = uuid.uuid4()
        chunk_id = uuid.uuid4()
        chunk_text = "Adani Ports owns Mundra Port."

        company = make_entity(EntityType.COMPANY, "Adani Ports")
        company.source_chunk = chunk_id
        port = make_entity(EntityType.PORT, "Mundra Port")
        port.source_chunk = chunk_id

        company_mention = make_mention(company.id, character_offset=chunk_text.index("Adani Ports"))
        port_mention = make_mention(port.id, character_offset=chunk_text.index("Mundra Port"))

        company_node_id = uuid.uuid4()
        port_node_id = uuid.uuid4()
        extraction_run = _extraction_run(run_id)

        agent = _agent(
            extraction_run_id=run_id,
            mentions={company.id: [company_mention], port.id: [port_mention]},
            chunks={chunk_id: _chunk(chunk_id, chunk_text)},
            extraction_run=extraction_run,
        )
        context = AgentContext(correlation_id="test")
        context.state["node_resolution"] = NodeResolutionOutput(
            node_plans=[],
            eligible_entities=[
                _eligible(company, company_node_id, "company:adani_ports"),
                _eligible(port, port_node_id, "port:mundra"),
            ],
            entities_skipped_ineligible_type=0,
            entities_skipped_unresolved=0,
            entities_skipped_no_confidence=0,
        )

        output = await agent.run(context)

        assert output.candidate_pairs_evaluated == 1
        assert len(output.findings) == 1
        finding = output.findings[0]
        assert finding.relationship_type == "owns"
        assert finding.source_node_id == company_node_id
        assert finding.target_node_id == port_node_id
        assert finding.chunk_id == chunk_id
        assert finding.document_id == extraction_run.document_id
        assert finding.prompt_hash == extraction_run.prompt_hash

    async def test_entities_without_source_chunk_are_excluded(self) -> None:
        run_id = uuid.uuid4()
        company = make_entity(EntityType.COMPANY, "Adani Ports")
        company.source_chunk = None
        port = make_entity(EntityType.PORT, "Mundra Port")
        port.source_chunk = None

        agent = _agent(
            extraction_run_id=run_id, mentions={}, chunks={}, extraction_run=_extraction_run(run_id)
        )
        context = AgentContext(correlation_id="test")
        context.state["node_resolution"] = NodeResolutionOutput(
            node_plans=[],
            eligible_entities=[
                _eligible(company, uuid.uuid4(), "company:adani_ports"),
                _eligible(port, uuid.uuid4(), "port:mundra"),
            ],
            entities_skipped_ineligible_type=0,
            entities_skipped_unresolved=0,
            entities_skipped_no_confidence=0,
        )

        output = await agent.run(context)

        assert output.findings == []
        assert output.candidate_pairs_evaluated == 0

    async def test_low_combined_confidence_is_discarded(self) -> None:
        run_id = uuid.uuid4()
        chunk_id = uuid.uuid4()
        chunk_text = "Contract SC-1 references thermal coal terms directly here."

        contract = make_entity(EntityType.CONTRACT, "SC-1")
        contract.source_chunk = chunk_id
        commodity = make_entity(EntityType.COMMODITY, "thermal coal")
        commodity.source_chunk = chunk_id

        contract_mention = make_mention(contract.id, character_offset=chunk_text.index("SC-1"))
        commodity_mention = make_mention(
            commodity.id, character_offset=chunk_text.index("thermal coal")
        )

        agent = _agent(
            extraction_run_id=run_id,
            mentions={contract.id: [contract_mention], commodity.id: [commodity_mention]},
            chunks={chunk_id: _chunk(chunk_id, chunk_text)},
            extraction_run=_extraction_run(run_id),
        )
        context = AgentContext(correlation_id="test")
        # references' base_confidence is 0.55 - two low-trust entities
        # (0.2 each) multiply down below MIN_EDGE_CONFIDENCE.
        context.state["node_resolution"] = NodeResolutionOutput(
            node_plans=[],
            eligible_entities=[
                _eligible(contract, uuid.uuid4(), "contract:sc-1", confidence=0.2),
                _eligible(commodity, uuid.uuid4(), "commodity:thermal_coal", confidence=0.2),
            ],
            entities_skipped_ineligible_type=0,
            entities_skipped_unresolved=0,
            entities_skipped_no_confidence=0,
        )

        output = await agent.run(context)

        assert output.findings == []
        assert output.discarded_low_confidence == 1
        assert 0.55 * 0.2 < MIN_EDGE_CONFIDENCE
