"""Data access for the knowledge graph: ontology/relationship-type
reference data, nodes, edges, evidence, and build-run tracking, plus the
recursive-CTE traversal queries (neighbors, subgraph, shortest path) that
back KnowledgeGraphService - see docs/ARCHITECTURE.md's Phase 4 section
for why this is hand-rolled SQL rather than a graph library.
"""

import uuid
from typing import Any

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.base_repository import BaseRepository
from app.modules.extraction.models import ExtractionStatus
from app.modules.graph.models import (
    GraphBuildRun,
    GraphEdge,
    GraphEvidence,
    GraphNode,
    GraphNodeStatus,
    OntologyType,
    RelationshipType,
)

_ACTIVE_BUILD_STATUSES = (ExtractionStatus.PENDING, ExtractionStatus.RUNNING)

# Following merged_into_id more than this many hops means either a data
# integrity bug (a merge cycle) or a pathological merge chain - treated
# as "cannot resolve" rather than looping forever.
_MAX_MERGE_CHAIN_HOPS = 10


class OntologyTypeRepository(BaseRepository[OntologyType]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, OntologyType)

    async def get_by_entity_type(self, entity_type: str) -> OntologyType | None:
        stmt = select(OntologyType).where(OntologyType.entity_type == entity_type)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_all(self) -> list[OntologyType]:
        result = await self.session.execute(select(OntologyType))
        return list(result.scalars().all())


class RelationshipTypeRepository(BaseRepository[RelationshipType]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, RelationshipType)

    async def get_by_name(self, relationship_name: str) -> RelationshipType | None:
        stmt = select(RelationshipType).where(
            RelationshipType.relationship_name == relationship_name
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_all(self) -> list[RelationshipType]:
        result = await self.session.execute(select(RelationshipType))
        return list(result.scalars().all())


class GraphNodeRepository(BaseRepository[GraphNode]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, GraphNode)

    async def get_by_canonical_id(self, canonical_id: str) -> GraphNode | None:
        stmt = select(GraphNode).where(GraphNode.canonical_id == canonical_id)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_by_ids(self, node_ids: list[uuid.UUID]) -> dict[uuid.UUID, GraphNode]:
        if not node_ids:
            return {}
        stmt = select(GraphNode).where(GraphNode.id.in_(node_ids))
        result = await self.session.execute(stmt)
        return {node.id: node for node in result.scalars().all()}

    async def list_nodes(
        self,
        *,
        node_type: str | None = None,
        status: GraphNodeStatus | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> list[GraphNode]:
        stmt = select(GraphNode)
        if node_type is not None:
            stmt = stmt.where(GraphNode.node_type == node_type)
        if status is not None:
            stmt = stmt.where(GraphNode.status == status)
        stmt = stmt.order_by(GraphNode.display_name.asc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_nodes(
        self, *, node_type: str | None = None, status: GraphNodeStatus | None = None
    ) -> int:
        stmt = select(func.count()).select_from(GraphNode)
        if node_type is not None:
            stmt = stmt.where(GraphNode.node_type == node_type)
        if status is not None:
            stmt = stmt.where(GraphNode.status == status)
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    async def resolve_active_node(self, node: GraphNode) -> GraphNode:
        """Follows merged_into_id until an ACTIVE node is reached. A node
        pointed at by an edge/evidence row created before a later merge
        is resolved to its live survivor rather than a tombstone."""
        current = node
        hops = 0
        while current.status == GraphNodeStatus.MERGED and current.merged_into_id is not None:
            if hops >= _MAX_MERGE_CHAIN_HOPS:
                return current
            next_node = await self.get_by_id(current.merged_into_id)
            if next_node is None:
                return current
            current = next_node
            hops += 1
        return current


class GraphEdgeRepository(BaseRepository[GraphEdge]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, GraphEdge)

    async def get_by_triple(
        self, source_node_id: uuid.UUID, target_node_id: uuid.UUID, relationship_type: str
    ) -> GraphEdge | None:
        stmt = select(GraphEdge).where(
            GraphEdge.source_node_id == source_node_id,
            GraphEdge.target_node_id == target_node_id,
            GraphEdge.relationship_type == relationship_type,
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_edges(
        self,
        *,
        relationship_type: str | None = None,
        node_id: uuid.UUID | None = None,
        min_confidence: float | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> list[GraphEdge]:
        stmt = select(GraphEdge)
        if relationship_type is not None:
            stmt = stmt.where(GraphEdge.relationship_type == relationship_type)
        if node_id is not None:
            stmt = stmt.where(
                (GraphEdge.source_node_id == node_id) | (GraphEdge.target_node_id == node_id)
            )
        if min_confidence is not None:
            stmt = stmt.where(GraphEdge.confidence >= min_confidence)
        stmt = stmt.order_by(GraphEdge.confidence.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_edges(
        self,
        *,
        relationship_type: str | None = None,
        node_id: uuid.UUID | None = None,
        min_confidence: float | None = None,
    ) -> int:
        stmt = select(func.count()).select_from(GraphEdge)
        if relationship_type is not None:
            stmt = stmt.where(GraphEdge.relationship_type == relationship_type)
        if node_id is not None:
            stmt = stmt.where(
                (GraphEdge.source_node_id == node_id) | (GraphEdge.target_node_id == node_id)
            )
        if min_confidence is not None:
            stmt = stmt.where(GraphEdge.confidence >= min_confidence)
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    async def list_for_node(self, node_id: uuid.UUID) -> list[GraphEdge]:
        """Every edge touching a node, either direction - used by
        GraphBuilderService.merge to re-point a merged node's edges onto
        its survivor."""
        stmt = select(GraphEdge).where(
            (GraphEdge.source_node_id == node_id) | (GraphEdge.target_node_id == node_id)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def neighbors(
        self, node_id: uuid.UUID, *, relationship_type: str | None = None, limit: int = 50
    ) -> list[GraphEdge]:
        """1-hop neighbors - a plain join, no recursion needed."""
        return await self.list_edges(
            relationship_type=relationship_type, node_id=node_id, limit=limit
        )

    async def reachable_node_ids(
        self, start_node_id: uuid.UUID, *, max_depth: int, relationship_type: str | None = None
    ) -> dict[uuid.UUID, int]:
        """Every node reachable from start_node_id within max_depth hops
        (edges treated as undirected for reachability), mapped to the
        minimum hop count to reach it. Powers subgraph generation."""
        # CAST(:param AS uuid), never :param::uuid - SQLAlchemy's text()
        # bind-parameter parser mishandles a `::` cast operator that
        # immediately follows a bind parameter with no space, silently
        # leaving the parameter unbound and producing a syntax error at
        # the database - confirmed against this exact asyncpg/SQLAlchemy
        # combination, not a hypothetical concern.
        type_filter = "AND e.relationship_type = :relationship_type" if relationship_type else ""
        sql = f"""
            WITH RECURSIVE traversal(node_id, depth, path) AS (
                SELECT CAST(:start_node_id AS uuid), 0, ARRAY[CAST(:start_node_id AS uuid)]
                UNION ALL
                SELECT o.other_id, t.depth + 1, t.path || o.other_id
                FROM traversal t
                JOIN graph_edges e
                    ON (e.source_node_id = t.node_id OR e.target_node_id = t.node_id)
                    {type_filter}
                CROSS JOIN LATERAL (
                    SELECT CASE WHEN e.source_node_id = t.node_id
                        THEN e.target_node_id ELSE e.source_node_id END AS other_id
                ) o
                WHERE t.depth < :max_depth AND NOT (o.other_id = ANY(t.path))
            )
            SELECT node_id, MIN(depth) AS depth
            FROM traversal
            WHERE depth > 0
            GROUP BY node_id
            ORDER BY depth ASC
        """
        params: dict[str, Any] = {"start_node_id": str(start_node_id), "max_depth": max_depth}
        if relationship_type:
            params["relationship_type"] = relationship_type
        result = await self.session.execute(text(sql), params)
        return {row.node_id: row.depth for row in result}

    async def shortest_path_node_ids(
        self,
        source_node_id: uuid.UUID,
        target_node_id: uuid.UUID,
        *,
        max_depth: int,
        relationship_type: str | None = None,
    ) -> list[uuid.UUID] | None:
        """The node-id sequence of a shortest (by hop count) undirected
        path from source to target, or None if unreachable within
        max_depth."""
        type_filter = "AND e.relationship_type = :relationship_type" if relationship_type else ""
        sql = f"""
            WITH RECURSIVE traversal(node_id, depth, path) AS (
                SELECT CAST(:source_node_id AS uuid), 0, ARRAY[CAST(:source_node_id AS uuid)]
                UNION ALL
                SELECT o.other_id, t.depth + 1, t.path || o.other_id
                FROM traversal t
                JOIN graph_edges e
                    ON (e.source_node_id = t.node_id OR e.target_node_id = t.node_id)
                    {type_filter}
                CROSS JOIN LATERAL (
                    SELECT CASE WHEN e.source_node_id = t.node_id
                        THEN e.target_node_id ELSE e.source_node_id END AS other_id
                ) o
                WHERE t.depth < :max_depth AND NOT (o.other_id = ANY(t.path))
            )
            SELECT path
            FROM traversal
            WHERE node_id = :target_node_id
            ORDER BY depth ASC
            LIMIT 1
        """
        params: dict[str, Any] = {
            "source_node_id": str(source_node_id),
            "target_node_id": str(target_node_id),
            "max_depth": max_depth,
        }
        if relationship_type:
            params["relationship_type"] = relationship_type
        result = await self.session.execute(text(sql), params)
        row = result.first()
        if row is None:
            return None
        return list(row.path)


class GraphEvidenceRepository(BaseRepository[GraphEvidence]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, GraphEvidence)

    async def bulk_create(self, items: list[GraphEvidence]) -> list[GraphEvidence]:
        self.session.add_all(items)
        await self.session.flush()
        return items

    async def list_for_edge(self, edge_id: uuid.UUID) -> list[GraphEvidence]:
        stmt = (
            select(GraphEvidence)
            .where(GraphEvidence.edge_id == edge_id)
            .order_by(GraphEvidence.created_at.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def existing_keys_for_edges(
        self, edge_ids: list[uuid.UUID]
    ) -> set[tuple[uuid.UUID, uuid.UUID, uuid.UUID | None]]:
        """The (edge_id, entity_id, chunk_id) keys already recorded for a
        set of edges - GraphBuilderService's idempotent-rebuild dedup
        check, so re-running a build on unchanged data never creates
        duplicate evidence rows or inflates evidence_count."""
        if not edge_ids:
            return set()
        stmt = select(
            GraphEvidence.edge_id, GraphEvidence.entity_id, GraphEvidence.chunk_id
        ).where(GraphEvidence.edge_id.in_(edge_ids))
        result = await self.session.execute(stmt)
        return {(row.edge_id, row.entity_id, row.chunk_id) for row in result}

    async def count_distinct_chunks_for_edge(self, edge_id: uuid.UUID) -> int:
        stmt = (
            select(func.count(func.distinct(GraphEvidence.chunk_id)))
            .select_from(GraphEvidence)
            .where(GraphEvidence.edge_id == edge_id)
        )
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    async def delete_for_edges(self, edge_ids: list[uuid.UUID]) -> None:
        if not edge_ids:
            return
        await self.session.execute(
            sa_delete(GraphEvidence).where(GraphEvidence.edge_id.in_(edge_ids))
        )
        await self.session.flush()


class GraphBuildRunRepository(BaseRepository[GraphBuildRun]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, GraphBuildRun)

    async def list_recent(self, *, offset: int = 0, limit: int = 20) -> list[GraphBuildRun]:
        stmt = (
            select(GraphBuildRun)
            .order_by(GraphBuildRun.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_recent(self) -> int:
        result = await self.session.execute(select(func.count()).select_from(GraphBuildRun))
        return int(result.scalar_one())

    async def get_active(self) -> GraphBuildRun | None:
        """Any build run still PENDING/RUNNING - the graph is one shared
        structure, so unlike trust (scoped per extraction_run_id), only
        one rebuild may be in flight at a time regardless of scope."""
        stmt = (
            select(GraphBuildRun).where(GraphBuildRun.status.in_(_ACTIVE_BUILD_STATUSES)).limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()
