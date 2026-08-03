"""Unit tests for KnowledgeGraphService: reads against mocked
repositories, and merge_nodes against lightweight in-memory fakes (it
chains enough get/update/delete calls that a stateful fake is far less
brittle than wiring individual AsyncMock return values)."""

import uuid
from unittest.mock import AsyncMock

import pytest

from app.core.exceptions import ConflictError, NotFoundError
from app.modules.graph.models import GraphEdge, GraphEvidence, GraphNode, GraphNodeStatus
from app.modules.graph.query_service import KnowledgeGraphService

pytestmark = pytest.mark.asyncio


def _node(
    node_id: uuid.UUID | None = None,
    *,
    status: GraphNodeStatus = GraphNodeStatus.ACTIVE,
    merged_into_id: uuid.UUID | None = None,
    aliases: list[str] | None = None,
    canonical_id: str = "company:x",
) -> GraphNode:
    return GraphNode(
        id=node_id or uuid.uuid4(),
        canonical_id=canonical_id,
        node_type="company",
        display_name=canonical_id,
        aliases_json=aliases or [],
        metadata_json={},
        status=status,
        merged_into_id=merged_into_id,
    )


def _edge(
    source: uuid.UUID,
    target: uuid.UUID,
    *,
    relationship_type: str = "owns",
    confidence: float = 0.7,
    edge_id: uuid.UUID | None = None,
) -> GraphEdge:
    return GraphEdge(
        id=edge_id or uuid.uuid4(),
        source_node_id=source,
        target_node_id=target,
        relationship_type=relationship_type,
        confidence=confidence,
        evidence_count=1,
        provenance_json={},
    )


def _service(**overrides: object) -> tuple[KnowledgeGraphService, dict[str, AsyncMock]]:
    mocks = {
        "node_repo": AsyncMock(),
        "edge_repo": AsyncMock(),
        "evidence_repo": AsyncMock(),
        "audit_service": AsyncMock(),
    }
    mocks.update(overrides)  # type: ignore[arg-type]
    service = KnowledgeGraphService(
        node_repo=mocks["node_repo"],
        edge_repo=mocks["edge_repo"],
        evidence_repo=mocks["evidence_repo"],
        audit_service=mocks["audit_service"],
    )
    return service, mocks


class TestNodeReads:
    async def test_list_nodes_returns_items_and_total(self) -> None:
        service, mocks = _service()
        mocks["node_repo"].list_nodes.return_value = [_node()]
        mocks["node_repo"].count_nodes.return_value = 1

        nodes, total = await service.list_nodes()

        assert len(nodes) == 1
        assert total == 1

    async def test_get_node_not_found_raises(self) -> None:
        service, mocks = _service()
        mocks["node_repo"].get_by_id.return_value = None

        with pytest.raises(NotFoundError):
            await service.get_node(uuid.uuid4())

    async def test_get_node_by_canonical_id_returns_tombstone_as_is(self) -> None:
        """A merged node is returned as-is (status visible), not
        silently redirected to its survivor."""
        service, mocks = _service()
        tombstone = _node(status=GraphNodeStatus.MERGED, merged_into_id=uuid.uuid4())
        mocks["node_repo"].get_by_canonical_id.return_value = tombstone

        result = await service.get_node_by_canonical_id("company:x")

        assert result is tombstone
        assert result.status == GraphNodeStatus.MERGED

    async def test_get_node_by_canonical_id_missing_raises(self) -> None:
        service, mocks = _service()
        mocks["node_repo"].get_by_canonical_id.return_value = None

        with pytest.raises(NotFoundError):
            await service.get_node_by_canonical_id("company:missing")


class TestEdgeReads:
    async def test_list_edges_returns_items_and_total(self) -> None:
        service, mocks = _service()
        mocks["edge_repo"].list_edges.return_value = [_edge(uuid.uuid4(), uuid.uuid4())]
        mocks["edge_repo"].count_edges.return_value = 1

        edges, total = await service.list_edges()

        assert len(edges) == 1
        assert total == 1

    async def test_get_edge_not_found_raises(self) -> None:
        service, mocks = _service()
        mocks["edge_repo"].get_by_id.return_value = None

        with pytest.raises(NotFoundError):
            await service.get_edge(uuid.uuid4())

    async def test_list_evidence_for_edge_checks_edge_exists_first(self) -> None:
        service, mocks = _service()
        mocks["edge_repo"].get_by_id.return_value = None

        with pytest.raises(NotFoundError):
            await service.list_evidence_for_edge(uuid.uuid4())
        mocks["evidence_repo"].list_for_edge.assert_not_awaited()

    async def test_relationships_for_canonical_id_resolves_node_then_lists_edges(self) -> None:
        service, mocks = _service()
        node = _node()
        mocks["node_repo"].get_by_canonical_id.return_value = node
        mocks["edge_repo"].list_edges.return_value = [_edge(node.id, uuid.uuid4())]

        edges = await service.relationships_for_canonical_id("company:x")

        assert len(edges) == 1
        assert mocks["edge_repo"].list_edges.await_args.kwargs["node_id"] == node.id


class TestTraversal:
    async def test_neighbors_checks_node_exists(self) -> None:
        service, mocks = _service()
        mocks["node_repo"].get_by_id.return_value = None

        with pytest.raises(NotFoundError):
            await service.neighbors(uuid.uuid4())

    async def test_subgraph_includes_center_and_reachable_nodes(self) -> None:
        service, mocks = _service()
        center = _node()
        neighbor = _node()
        mocks["node_repo"].get_by_id.return_value = center
        mocks["edge_repo"].reachable_node_ids.return_value = {neighbor.id: 1}
        mocks["node_repo"].list_by_ids.return_value = {center.id: center, neighbor.id: neighbor}
        edge = _edge(center.id, neighbor.id)
        mocks["edge_repo"].list_edges.return_value = [edge]

        result = await service.subgraph(center.id, depth=2)

        assert result.center is center
        assert {n.id for n in result.nodes} == {center.id, neighbor.id}
        assert result.edges == [edge]

    async def test_subgraph_excludes_edges_reaching_outside_the_set(self) -> None:
        service, mocks = _service()
        center = _node()
        outside_id = uuid.uuid4()
        mocks["node_repo"].get_by_id.return_value = center
        mocks["edge_repo"].reachable_node_ids.return_value = {}
        mocks["node_repo"].list_by_ids.return_value = {center.id: center}
        mocks["edge_repo"].list_edges.return_value = [_edge(center.id, outside_id)]

        result = await service.subgraph(center.id, depth=1)

        assert result.edges == []

    async def test_shortest_path_returns_none_when_unreachable(self) -> None:
        service, mocks = _service()
        source = _node(canonical_id="company:a")
        target = _node(canonical_id="company:b")
        mocks["node_repo"].get_by_canonical_id.side_effect = [source, target]
        mocks["edge_repo"].shortest_path_node_ids.return_value = None

        result = await service.shortest_path("company:a", "company:b")

        assert result is None

    async def test_shortest_path_returns_nodes_and_hop_edges(self) -> None:
        service, mocks = _service()
        a, b, c = _node(), _node(), _node()
        mocks["node_repo"].get_by_canonical_id.side_effect = [a, c]
        mocks["edge_repo"].shortest_path_node_ids.return_value = [a.id, b.id, c.id]
        mocks["node_repo"].list_by_ids.return_value = {a.id: a, b.id: b, c.id: c}
        edge_ab = _edge(a.id, b.id, confidence=0.6)
        edge_bc = _edge(b.id, c.id, confidence=0.8)

        async def _list_edges(
            *, relationship_type: object, node_id: uuid.UUID, limit: int
        ) -> list[GraphEdge]:
            if node_id == a.id:
                return [edge_ab]
            if node_id == b.id:
                return [edge_ab, edge_bc]
            return []

        mocks["edge_repo"].list_edges.side_effect = _list_edges

        result = await service.shortest_path("company:a", "company:c")

        assert result is not None
        assert [n.id for n in result.nodes] == [a.id, b.id, c.id]
        assert result.edges == [edge_ab, edge_bc]


class _FakeNodeRepo:
    def __init__(self, nodes: list[GraphNode]) -> None:
        self.nodes = {n.id: n for n in nodes}

    async def get_by_id(self, node_id: uuid.UUID) -> GraphNode | None:
        return self.nodes.get(node_id)

    async def resolve_active_node(self, node: GraphNode) -> GraphNode:
        current = node
        while current.status == GraphNodeStatus.MERGED and current.merged_into_id is not None:
            current = self.nodes[current.merged_into_id]
        return current

    async def update(self, node: GraphNode, **fields: object) -> GraphNode:
        for key, value in fields.items():
            setattr(node, key, value)
        return node


class _FakeEdgeRepo:
    def __init__(self, edges: list[GraphEdge]) -> None:
        self.edges = {e.id: e for e in edges}
        self.deleted: list[uuid.UUID] = []

    async def list_for_node(self, node_id: uuid.UUID) -> list[GraphEdge]:
        return [e for e in self.edges.values() if node_id in (e.source_node_id, e.target_node_id)]

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

    async def update(self, edge: GraphEdge, **fields: object) -> GraphEdge:
        for key, value in fields.items():
            setattr(edge, key, value)
        return edge

    async def delete(self, edge: GraphEdge) -> None:
        self.deleted.append(edge.id)
        del self.edges[edge.id]


class _FakeEvidenceRepo:
    def __init__(self, rows: list[GraphEvidence] | None = None) -> None:
        self.rows = rows or []

    async def delete_for_edges(self, edge_ids: list[uuid.UUID]) -> None:
        self.rows = [r for r in self.rows if r.edge_id not in edge_ids]

    async def list_for_edge(self, edge_id: uuid.UUID) -> list[GraphEvidence]:
        return [r for r in self.rows if r.edge_id == edge_id]

    async def update(self, row: GraphEvidence, **fields: object) -> GraphEvidence:
        for key, value in fields.items():
            setattr(row, key, value)
        return row

    async def count_distinct_chunks_for_edge(self, edge_id: uuid.UUID) -> int:
        return len({r.chunk_id for r in self.rows if r.edge_id == edge_id})


class TestMergeNodes:
    async def test_merging_a_node_into_itself_raises_conflict(self) -> None:
        node_id = uuid.uuid4()
        service, mocks = _service(
            node_repo=_FakeNodeRepo([_node(node_id)]),
            edge_repo=_FakeEdgeRepo([]),
            evidence_repo=_FakeEvidenceRepo(),
        )
        with pytest.raises(ConflictError):
            await service.merge_nodes(node_id, node_id, requested_by=uuid.uuid4())

    async def test_merging_an_already_merged_node_raises_conflict(self) -> None:
        target = _node()
        source = _node(status=GraphNodeStatus.MERGED, merged_into_id=target.id)
        service, mocks = _service(
            node_repo=_FakeNodeRepo([source, target]),
            edge_repo=_FakeEdgeRepo([]),
            evidence_repo=_FakeEvidenceRepo(),
        )
        with pytest.raises(ConflictError):
            await service.merge_nodes(source.id, target.id, requested_by=uuid.uuid4())

    async def test_simple_merge_tombstones_source_and_merges_aliases(self) -> None:
        source = _node(aliases=["X Ltd"], canonical_id="company:x_ltd")
        target = _node(aliases=["X"], canonical_id="company:x")
        service, mocks = _service(
            node_repo=_FakeNodeRepo([source, target]),
            edge_repo=_FakeEdgeRepo([]),
            evidence_repo=_FakeEvidenceRepo(),
        )

        result = await service.merge_nodes(source.id, target.id, requested_by=uuid.uuid4())

        assert result is target
        assert source.status == GraphNodeStatus.MERGED
        assert source.merged_into_id == target.id
        assert set(target.aliases_json) == {"X", "X Ltd", "company:x_ltd"}
        mocks["audit_service"].record.assert_awaited_once()

    async def test_source_edge_is_repointed_to_target(self) -> None:
        source = _node()
        target = _node()
        other = _node()
        edge = _edge(source.id, other.id, relationship_type="owns")
        edge_repo = _FakeEdgeRepo([edge])
        service, _mocks = _service(
            node_repo=_FakeNodeRepo([source, target, other]),
            edge_repo=edge_repo,
            evidence_repo=_FakeEvidenceRepo(),
        )

        await service.merge_nodes(source.id, target.id, requested_by=uuid.uuid4())

        assert edge.source_node_id == target.id
        assert edge.target_node_id == other.id

    async def test_edge_that_would_become_a_self_loop_is_dropped(self) -> None:
        source = _node()
        target = _node()
        self_loop_after_merge = _edge(source.id, target.id, relationship_type="owns")
        edge_repo = _FakeEdgeRepo([self_loop_after_merge])
        service, _mocks = _service(
            node_repo=_FakeNodeRepo([source, target]),
            edge_repo=edge_repo,
            evidence_repo=_FakeEvidenceRepo(),
        )

        await service.merge_nodes(source.id, target.id, requested_by=uuid.uuid4())

        assert self_loop_after_merge.id in edge_repo.deleted

    async def test_duplicate_edge_after_repoint_merges_into_survivor(self) -> None:
        source = _node()
        target = _node()
        other = _node()
        source_edge = _edge(source.id, other.id, relationship_type="owns", confidence=0.5)
        target_edge = _edge(target.id, other.id, relationship_type="owns", confidence=0.9)
        edge_repo = _FakeEdgeRepo([source_edge, target_edge])
        evidence_row = GraphEvidence(
            id=uuid.uuid4(),
            edge_id=source_edge.id,
            document_id=uuid.uuid4(),
            extraction_run_id=uuid.uuid4(),
            entity_id=uuid.uuid4(),
            page_number=1,
            chunk_id=uuid.uuid4(),
            prompt_hash="a" * 64,
        )
        evidence_repo = _FakeEvidenceRepo([evidence_row])
        service, _mocks = _service(
            node_repo=_FakeNodeRepo([source, target, other]),
            edge_repo=edge_repo,
            evidence_repo=evidence_repo,
        )

        await service.merge_nodes(source.id, target.id, requested_by=uuid.uuid4())

        # source_edge was deleted, its evidence re-pointed to target_edge
        assert source_edge.id not in edge_repo.edges
        assert target_edge.confidence == 0.9
        assert evidence_row.edge_id == target_edge.id
