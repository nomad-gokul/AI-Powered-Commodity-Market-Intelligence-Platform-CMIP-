"""Unit tests for PersistGraphResultsAgent against lightweight in-memory
fake repositories - real-database persistence correctness is covered by
the integration suite; this tests the agent's own upsert/dedup logic
(get-or-create edges, idempotent evidence, evidence_count recompute)."""

import uuid

import pytest
from shared.agent_contracts import AgentContext

from app.modules.graph.agents.persist_graph_results_agent import PersistGraphResultsAgent
from app.modules.graph.agents.schemas import (
    NodeResolutionOutput,
    NodeUpsertPlan,
    RelationshipExtractionOutput,
    ResolvedFinding,
)
from app.modules.graph.models import GraphEdge, GraphEvidence, GraphNode, GraphNodeStatus

pytestmark = pytest.mark.asyncio


class _FakeNodeRepo:
    def __init__(self) -> None:
        self.nodes: dict[uuid.UUID, GraphNode] = {}

    async def create(self, node: GraphNode) -> GraphNode:
        self.nodes[node.id] = node
        return node

    async def get_by_id(self, node_id: uuid.UUID) -> GraphNode | None:
        return self.nodes.get(node_id)

    async def update(self, node: GraphNode, **fields: object) -> GraphNode:
        for key, value in fields.items():
            setattr(node, key, value)
        return node


class _FakeEdgeRepo:
    def __init__(self) -> None:
        self.edges: dict[uuid.UUID, GraphEdge] = {}
        self.create_calls = 0
        self.update_calls = 0

    async def get_by_triple(
        self, source_node_id: uuid.UUID, target_node_id: uuid.UUID, relationship_type: str
    ) -> GraphEdge | None:
        for edge in self.edges.values():
            if (
                edge.source_node_id == source_node_id
                and edge.target_node_id == target_node_id
                and edge.relationship_type == relationship_type
            ):
                return edge
        return None

    async def create(self, edge: GraphEdge) -> GraphEdge:
        if edge.id is None:
            edge.id = uuid.uuid4()
        self.edges[edge.id] = edge
        self.create_calls += 1
        return edge

    async def update(self, edge: GraphEdge, **fields: object) -> GraphEdge:
        for key, value in fields.items():
            setattr(edge, key, value)
        self.update_calls += 1
        return edge


class _FakeEvidenceRepo:
    def __init__(self) -> None:
        self.rows: list[GraphEvidence] = []

    async def existing_keys_for_edges(
        self, edge_ids: list[uuid.UUID]
    ) -> set[tuple[uuid.UUID, uuid.UUID, uuid.UUID | None]]:
        return {
            (row.edge_id, row.entity_id, row.chunk_id)
            for row in self.rows
            if row.edge_id in edge_ids
        }

    async def bulk_create(self, items: list[GraphEvidence]) -> list[GraphEvidence]:
        self.rows.extend(items)
        return items

    async def count_distinct_chunks_for_edge(self, edge_id: uuid.UUID) -> int:
        return len({row.chunk_id for row in self.rows if row.edge_id == edge_id})


def _node_plan(
    *, node_id: uuid.UUID, canonical_id: str, is_new: bool, aliases: set[str]
) -> NodeUpsertPlan:
    return NodeUpsertPlan(
        node_id=node_id,
        canonical_id=canonical_id,
        node_type="company",
        display_name=canonical_id,
        is_new=is_new,
        existing_status=None if is_new else GraphNodeStatus.ACTIVE,
        new_aliases=frozenset(aliases),
    )


def _finding(
    *,
    source_node_id: uuid.UUID,
    target_node_id: uuid.UUID,
    relationship_type: str = "owns",
    confidence: float = 0.75,
    chunk_id: uuid.UUID | None = None,
) -> ResolvedFinding:
    return ResolvedFinding(
        relationship_type=relationship_type,
        source_node_id=source_node_id,
        target_node_id=target_node_id,
        confidence=confidence,
        evidence_type="text_pattern",
        matched_text="owns",
        source_entity_id=uuid.uuid4(),
        target_entity_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        extraction_run_id=uuid.uuid4(),
        chunk_id=chunk_id or uuid.uuid4(),
        source_page_number=1,
        target_page_number=1,
        prompt_hash="a" * 64,
    )


def _context(
    node_output: NodeResolutionOutput, relationship_output: RelationshipExtractionOutput
) -> AgentContext:
    context = AgentContext(correlation_id="test")
    context.state["node_resolution"] = node_output
    context.state["relationship_extraction"] = relationship_output
    return context


def _empty_node_output(plans: list[NodeUpsertPlan] | None = None) -> NodeResolutionOutput:
    return NodeResolutionOutput(
        node_plans=plans or [],
        eligible_entities=[],
        entities_skipped_ineligible_type=0,
        entities_skipped_unresolved=0,
        entities_skipped_no_confidence=0,
    )


def _no_findings() -> RelationshipExtractionOutput:
    return RelationshipExtractionOutput(
        findings=[], candidate_pairs_evaluated=0, discarded_low_confidence=0
    )


def _agent(
    *,
    node_repo: _FakeNodeRepo | None = None,
    edge_repo: _FakeEdgeRepo | None = None,
    evidence_repo: _FakeEvidenceRepo | None = None,
) -> PersistGraphResultsAgent:
    return PersistGraphResultsAgent(
        node_repo=node_repo or _FakeNodeRepo(),
        edge_repo=edge_repo or _FakeEdgeRepo(),
        evidence_repo=evidence_repo or _FakeEvidenceRepo(),
    )


class TestPersistGraphResultsAgent:
    async def test_name(self) -> None:
        assert _agent().name == "persist_graph_results"

    async def test_new_node_plan_creates_a_node(self) -> None:
        node_repo = _FakeNodeRepo()
        agent = _agent(node_repo=node_repo)
        node_id = uuid.uuid4()
        plan = _node_plan(node_id=node_id, canonical_id="company:x", is_new=True, aliases={"X"})
        output = await agent.run(_context(_empty_node_output([plan]), _no_findings()))

        assert output.nodes_created == 1
        assert node_id in node_repo.nodes
        assert node_repo.nodes[node_id].aliases_json == ["X"]

    async def test_existing_node_with_new_alias_is_updated(self) -> None:
        node_repo = _FakeNodeRepo()
        node_id = uuid.uuid4()
        node_repo.nodes[node_id] = GraphNode(
            id=node_id,
            canonical_id="company:x",
            node_type="company",
            display_name="X",
            aliases_json=["X"],
            metadata_json={},
            status=GraphNodeStatus.ACTIVE,
            merged_into_id=None,
        )
        agent = _agent(node_repo=node_repo)
        plan = _node_plan(
            node_id=node_id, canonical_id="company:x", is_new=False, aliases={"X Ltd"}
        )
        output = await agent.run(_context(_empty_node_output([plan]), _no_findings()))

        assert output.nodes_created == 0
        assert output.nodes_updated == 1
        assert node_repo.nodes[node_id].aliases_json == ["X", "X Ltd"]

    async def test_existing_node_with_no_new_alias_is_not_updated(self) -> None:
        node_repo = _FakeNodeRepo()
        node_id = uuid.uuid4()
        agent = _agent(node_repo=node_repo)
        plan = _node_plan(node_id=node_id, canonical_id="company:x", is_new=False, aliases=set())
        output = await agent.run(_context(_empty_node_output([plan]), _no_findings()))

        assert output.nodes_updated == 0

    async def test_new_finding_creates_edge_and_two_evidence_rows(self) -> None:
        edge_repo = _FakeEdgeRepo()
        agent = _agent(edge_repo=edge_repo)
        source_id, target_id = uuid.uuid4(), uuid.uuid4()
        finding = _finding(source_node_id=source_id, target_node_id=target_id)
        findings = RelationshipExtractionOutput(
            findings=[finding], candidate_pairs_evaluated=1, discarded_low_confidence=0
        )

        output = await agent.run(_context(_empty_node_output(), findings))

        assert output.edges_created == 1
        assert output.edges_updated == 0
        assert output.evidence_created == 2
        edge = next(iter(edge_repo.edges.values()))
        assert edge.confidence == finding.confidence
        assert edge.evidence_count == 1

    async def test_second_finding_for_same_triple_upserts_not_duplicates(self) -> None:
        edge_repo = _FakeEdgeRepo()
        agent = _agent(edge_repo=edge_repo)
        source_id, target_id = uuid.uuid4(), uuid.uuid4()
        first = _finding(source_node_id=source_id, target_node_id=target_id, confidence=0.6)
        second = _finding(source_node_id=source_id, target_node_id=target_id, confidence=0.9)
        findings = RelationshipExtractionOutput(
            findings=[first, second], candidate_pairs_evaluated=2, discarded_low_confidence=0
        )

        output = await agent.run(_context(_empty_node_output(), findings))

        assert output.edges_created == 1
        assert output.edges_updated == 0  # one edge total, touched twice within the same run
        assert len(edge_repo.edges) == 1
        edge = next(iter(edge_repo.edges.values()))
        # Confidence reflects the strongest evidence seen, never diluted
        # by a weaker duplicate.
        assert edge.confidence == 0.9
        assert output.evidence_created == 4  # 2 entities x 2 distinct chunk_ids
        assert edge.evidence_count == 2

    async def test_rebuild_on_unchanged_data_is_idempotent(self) -> None:
        """Re-running a build with the exact same finding (same chunk_id,
        same entities) a second time must not duplicate evidence or
        inflate evidence_count."""
        edge_repo = _FakeEdgeRepo()
        evidence_repo = _FakeEvidenceRepo()
        source_id, target_id = uuid.uuid4(), uuid.uuid4()
        chunk_id = uuid.uuid4()
        finding = _finding(source_node_id=source_id, target_node_id=target_id, chunk_id=chunk_id)

        agent = _agent(edge_repo=edge_repo, evidence_repo=evidence_repo)
        relationship_output = RelationshipExtractionOutput(
            findings=[finding], candidate_pairs_evaluated=1, discarded_low_confidence=0
        )
        first_run = await agent.run(_context(_empty_node_output(), relationship_output))
        second_run = await agent.run(_context(_empty_node_output(), relationship_output))

        assert first_run.edges_created == 1
        assert second_run.edges_created == 0
        assert second_run.evidence_created == 0
        edge = next(iter(edge_repo.edges.values()))
        assert edge.evidence_count == 1
        assert len(evidence_repo.rows) == 2
