"""Unit tests for GraphExpansion against a mocked KnowledgeGraphService -
no real database, no real recursive-CTE traversal (that's covered by
graph's own integration tests; this module only wraps the service call
and derives hop distance from its result)."""

import uuid
from unittest.mock import AsyncMock

import pytest

from app.core.exceptions import NotFoundError
from app.modules.graph.models import GraphEdge, GraphNode, GraphNodeStatus
from app.modules.graph.query_service import SubgraphResult
from app.modules.retrieval.graph_expansion import GraphExpansion

pytestmark = pytest.mark.asyncio


def _node(canonical_id: str, *, node_id: uuid.UUID | None = None) -> GraphNode:
    return GraphNode(
        id=node_id or uuid.uuid4(),
        canonical_id=canonical_id,
        node_type="company",
        display_name=canonical_id,
        aliases_json=[],
        metadata_json={},
        status=GraphNodeStatus.ACTIVE,
    )


def _edge(source: uuid.UUID, target: uuid.UUID) -> GraphEdge:
    return GraphEdge(
        id=uuid.uuid4(),
        source_node_id=source,
        target_node_id=target,
        relationship_type="owns",
        confidence=0.9,
        evidence_count=1,
        provenance_json={},
    )


class TestExpand:
    async def test_skips_unresolvable_seeds(self) -> None:
        service = AsyncMock()
        service.get_node_by_canonical_id.side_effect = NotFoundError("no such node")
        expansion = GraphExpansion(service)

        result = await expansion.expand(["company:unknown"])

        assert result.nodes == []
        assert result.edges == []

    async def test_resolves_seed_and_returns_subgraph(self) -> None:
        seed = _node("company:adani_ports_sez")
        neighbor = _node("port:mundra")
        edge = _edge(seed.id, neighbor.id)

        service = AsyncMock()
        service.get_node_by_canonical_id.return_value = seed
        service.subgraph.return_value = SubgraphResult(
            center=seed, nodes=[seed, neighbor], edges=[edge]
        )
        expansion = GraphExpansion(service)

        result = await expansion.expand(["company:adani_ports_sez"], depth=2)

        assert {hit.node.id for hit in result.nodes} == {seed.id, neighbor.id}
        assert result.edges == [edge]

    async def test_computes_hop_distance_via_bfs(self) -> None:
        seed = _node("company:a")
        one_hop = _node("port:b")
        two_hop = _node("country:c")
        edges = [_edge(seed.id, one_hop.id), _edge(one_hop.id, two_hop.id)]

        service = AsyncMock()
        service.get_node_by_canonical_id.return_value = seed
        service.subgraph.return_value = SubgraphResult(
            center=seed, nodes=[seed, one_hop, two_hop], edges=edges
        )
        expansion = GraphExpansion(service)

        result = await expansion.expand(["company:a"])

        hop_by_id = {hit.node.id: hit.hop_distance for hit in result.nodes}
        assert hop_by_id[seed.id] == 0
        assert hop_by_id[one_hop.id] == 1
        assert hop_by_id[two_hop.id] == 2

    async def test_deduplicates_nodes_reached_from_multiple_seeds_keeping_shortest_hop(
        self,
    ) -> None:
        seed_a = _node("company:a")
        seed_b = _node("company:b")
        shared = _node("port:shared")

        service = AsyncMock()
        service.get_node_by_canonical_id.side_effect = [seed_a, seed_b]
        service.subgraph.side_effect = [
            SubgraphResult(
                center=seed_a,
                nodes=[seed_a, shared],
                edges=[_edge(seed_a.id, shared.id)],
            ),
            SubgraphResult(
                center=seed_b, nodes=[seed_b, shared], edges=[_edge(seed_b.id, shared.id)]
            ),
        ]
        expansion = GraphExpansion(service)

        result = await expansion.expand(["company:a", "company:b"])

        shared_hits = [hit for hit in result.nodes if hit.node.id == shared.id]
        assert len(shared_hits) == 1
        assert shared_hits[0].hop_distance == 1
