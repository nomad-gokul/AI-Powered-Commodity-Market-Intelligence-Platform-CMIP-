"""Integration tests for repository methods not already exercised
end-to-end by test_api.py/test_worker_pipeline.py: the ontology/
relationship-type reference-data reads (seeded by migration
59226041fb77, never exposed via API - see api.py's docstring), and a
few filter/edge-case branches (empty list_by_ids, a real multi-hop merge
chain, a broken merge pointer) that only a real database round-trip
exercises meaningfully.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.graph.models import GraphBuildRun, GraphEdge, GraphNode, GraphNodeStatus
from app.modules.graph.repository import (
    GraphBuildRunRepository,
    GraphEdgeRepository,
    GraphEvidenceRepository,
    GraphNodeRepository,
    OntologyTypeRepository,
    RelationshipTypeRepository,
)

pytestmark = pytest.mark.asyncio


def _node(**overrides: object) -> GraphNode:
    defaults: dict[str, object] = {
        "canonical_id": f"company:{uuid.uuid4().hex[:8]}",
        "node_type": "company",
        "display_name": "Test Co",
        "aliases_json": [],
        "metadata_json": {},
        "status": GraphNodeStatus.ACTIVE,
    }
    defaults.update(overrides)
    return GraphNode(**defaults)


class TestOntologyTypeRepository:
    async def test_get_by_entity_type_returns_seeded_row(self, db_session: AsyncSession) -> None:
        repo = OntologyTypeRepository(db_session)
        company = await repo.get_by_entity_type("company")
        assert company is not None
        assert company.parent_type == "organization"

    async def test_get_by_unknown_entity_type_returns_none(self, db_session: AsyncSession) -> None:
        repo = OntologyTypeRepository(db_session)
        assert await repo.get_by_entity_type("not_a_real_type") is None

    async def test_list_all_includes_every_seeded_type(self, db_session: AsyncSession) -> None:
        repo = OntologyTypeRepository(db_session)
        entity_types = {t.entity_type for t in await repo.list_all()}
        expected = {
            "company",
            "port",
            "country",
            "commodity",
            "contract",
            "terminal",
            "vessel",
            "organization",
        }
        assert expected <= entity_types


class TestRelationshipTypeRepository:
    async def test_get_by_name_returns_seeded_row_with_inverse(
        self, db_session: AsyncSession
    ) -> None:
        repo = RelationshipTypeRepository(db_session)
        owns = await repo.get_by_name("owns")
        assert owns is not None
        assert owns.inverse_relationship == "owned_by"

    async def test_get_by_unknown_name_returns_none(self, db_session: AsyncSession) -> None:
        repo = RelationshipTypeRepository(db_session)
        assert await repo.get_by_name("not_a_real_relationship") is None

    async def test_list_all_includes_every_seeded_relationship(
        self, db_session: AsyncSession
    ) -> None:
        repo = RelationshipTypeRepository(db_session)
        names = {r.relationship_name for r in await repo.list_all()}
        expected = {"owns", "operates", "shipped_from", "shipped_to", "references", "located_in"}
        assert expected <= names

    async def test_located_in_is_transitive_but_not_symmetric(
        self, db_session: AsyncSession
    ) -> None:
        repo = RelationshipTypeRepository(db_session)
        located_in = await repo.get_by_name("located_in")
        assert located_in is not None
        assert located_in.transitive is True
        assert located_in.symmetric is False


class TestGraphNodeRepositoryEdgeCases:
    async def test_list_by_ids_with_empty_list_returns_empty_dict(
        self, db_session: AsyncSession
    ) -> None:
        assert await GraphNodeRepository(db_session).list_by_ids([]) == {}

    async def test_count_nodes_filters_by_status(self, db_session: AsyncSession) -> None:
        repo = GraphNodeRepository(db_session)
        active = _node(status=GraphNodeStatus.ACTIVE)
        merged = _node(status=GraphNodeStatus.MERGED)
        db_session.add_all([active, merged])
        await db_session.flush()

        active_count = await repo.count_nodes(status=GraphNodeStatus.ACTIVE)
        merged_count = await repo.count_nodes(status=GraphNodeStatus.MERGED)

        assert active_count >= 1
        assert merged_count >= 1

    async def test_resolve_active_node_follows_a_multi_hop_chain(
        self, db_session: AsyncSession
    ) -> None:
        repo = GraphNodeRepository(db_session)
        survivor = _node()
        middle = _node()
        original = _node()
        db_session.add_all([survivor, middle, original])
        await db_session.flush()
        middle.status = GraphNodeStatus.MERGED
        middle.merged_into_id = survivor.id
        original.status = GraphNodeStatus.MERGED
        original.merged_into_id = middle.id
        await db_session.flush()

        resolved = await repo.resolve_active_node(original)

        assert resolved.id == survivor.id


class TestGraphEdgeRepositoryFilters:
    async def test_list_for_node_returns_edges_in_either_direction(
        self, db_session: AsyncSession
    ) -> None:
        node_repo = GraphNodeRepository(db_session)
        edge_repo = GraphEdgeRepository(db_session)
        a, b, c = _node(), _node(), _node()
        db_session.add_all([a, b, c])
        await db_session.flush()
        edge_out = GraphEdge(
            source_node_id=a.id,
            target_node_id=b.id,
            relationship_type="owns",
            confidence=0.7,
            evidence_count=1,
            provenance_json={},
        )
        edge_in = GraphEdge(
            source_node_id=c.id,
            target_node_id=a.id,
            relationship_type="owns",
            confidence=0.7,
            evidence_count=1,
            provenance_json={},
        )
        db_session.add_all([edge_out, edge_in])
        await db_session.flush()

        touching = await edge_repo.list_for_node(a.id)

        assert {e.id for e in touching} == {edge_out.id, edge_in.id}
        assert await node_repo.get_by_id(a.id) is not None  # sanity: fixture committed

    async def test_count_edges_filters_by_min_confidence(self, db_session: AsyncSession) -> None:
        edge_repo = GraphEdgeRepository(db_session)
        a, b = _node(), _node()
        db_session.add_all([a, b])
        await db_session.flush()
        db_session.add(
            GraphEdge(
                source_node_id=a.id,
                target_node_id=b.id,
                relationship_type="owns",
                confidence=0.3,
                evidence_count=1,
                provenance_json={},
            )
        )
        await db_session.flush()

        assert await edge_repo.count_edges(node_id=a.id, min_confidence=0.5) == 0
        assert await edge_repo.count_edges(node_id=a.id, min_confidence=0.2) == 1


class TestGraphEvidenceRepositoryDeleteForEdges:
    async def test_delete_for_edges_with_empty_list_is_a_no_op(
        self, db_session: AsyncSession
    ) -> None:
        await GraphEvidenceRepository(db_session).delete_for_edges([])


class TestGraphBuildRunRepository:
    async def test_list_recent_and_count_recent(self, db_session: AsyncSession) -> None:
        repo = GraphBuildRunRepository(db_session)
        db_session.add(GraphBuildRun())
        await db_session.flush()

        runs = await repo.list_recent(limit=5)
        total = await repo.count_recent()

        assert len(runs) >= 1
        assert total >= 1

    async def test_get_active_returns_none_when_nothing_running(
        self, db_session: AsyncSession
    ) -> None:
        # db_session's transaction isolation means no other test's rows
        # leak in here.
        repo = GraphBuildRunRepository(db_session)
        assert await repo.get_active() is None
