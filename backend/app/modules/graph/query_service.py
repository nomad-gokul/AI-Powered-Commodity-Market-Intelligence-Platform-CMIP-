"""KnowledgeGraphService: the class the Phase 4 spec names directly, with
exactly its stated responsibilities - traversal, merge, expansion,
filtering, relationship validation. Everything here is a read (or, for
merge_nodes, a bounded correction) over an already-built graph; nothing
here builds the graph itself - that's GraphBuilderService's job.
"""

import uuid
from dataclasses import dataclass

from app.core.exceptions import ConflictError, NotFoundError
from app.modules.audit.service import AuditService
from app.modules.graph.models import GraphEdge, GraphEvidence, GraphNode, GraphNodeStatus
from app.modules.graph.repository import (
    GraphEdgeRepository,
    GraphEvidenceRepository,
    GraphNodeRepository,
)

# Traversal (subgraph, shortest path) is bounded at this many hops -
# unbounded BFS/path search over a corpus-wide graph has no natural stop
# condition otherwise. Callers may ask for less; never more.
MAX_TRAVERSAL_DEPTH = 6


@dataclass(frozen=True, slots=True)
class SubgraphResult:
    center: GraphNode
    nodes: list[GraphNode]
    edges: list[GraphEdge]


@dataclass(frozen=True, slots=True)
class PathResult:
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class KnowledgeGraphService:
    def __init__(
        self,
        *,
        node_repo: GraphNodeRepository,
        edge_repo: GraphEdgeRepository,
        evidence_repo: GraphEvidenceRepository,
        audit_service: AuditService,
    ) -> None:
        self.node_repo = node_repo
        self.edge_repo = edge_repo
        self.evidence_repo = evidence_repo
        self.audit_service = audit_service

    # -- nodes ---------------------------------------------------------

    async def list_nodes(
        self,
        *,
        node_type: str | None = None,
        status: GraphNodeStatus | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[GraphNode], int]:
        nodes = await self.node_repo.list_nodes(
            node_type=node_type, status=status, offset=offset, limit=limit
        )
        total = await self.node_repo.count_nodes(node_type=node_type, status=status)
        return nodes, total

    async def get_node(self, node_id: uuid.UUID) -> GraphNode:
        node = await self.node_repo.get_by_id(node_id)
        if node is None:
            raise NotFoundError(f"Graph node {node_id} not found")
        return node

    async def get_node_by_canonical_id(self, canonical_id: str) -> GraphNode:
        """Returns the node record for this canonical_id as-is, including
        a tombstoned (status=MERGED) one - callers see the merge, and can
        follow merged_into_id themselves, rather than being silently
        redirected to a different record than the one they asked for."""
        node = await self.node_repo.get_by_canonical_id(canonical_id)
        if node is None:
            raise NotFoundError(f"No graph node for canonical_id {canonical_id!r}")
        return node

    # -- edges -----------------------------------------------------------

    async def list_edges(
        self,
        *,
        relationship_type: str | None = None,
        node_id: uuid.UUID | None = None,
        min_confidence: float | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[GraphEdge], int]:
        edges = await self.edge_repo.list_edges(
            relationship_type=relationship_type,
            node_id=node_id,
            min_confidence=min_confidence,
            offset=offset,
            limit=limit,
        )
        total = await self.edge_repo.count_edges(
            relationship_type=relationship_type, node_id=node_id, min_confidence=min_confidence
        )
        return edges, total

    async def get_edge(self, edge_id: uuid.UUID) -> GraphEdge:
        edge = await self.edge_repo.get_by_id(edge_id)
        if edge is None:
            raise NotFoundError(f"Graph edge {edge_id} not found")
        return edge

    async def list_evidence_for_edge(self, edge_id: uuid.UUID) -> list[GraphEvidence]:
        await self.get_edge(edge_id)
        return await self.evidence_repo.list_for_edge(edge_id)

    async def relationships_for_canonical_id(
        self, canonical_id: str, *, relationship_type: str | None = None
    ) -> list[GraphEdge]:
        node = await self.get_node_by_canonical_id(canonical_id)
        return await self.edge_repo.list_edges(
            relationship_type=relationship_type, node_id=node.id, limit=500
        )

    # -- traversal -------------------------------------------------------

    async def neighbors(
        self, node_id: uuid.UUID, *, relationship_type: str | None = None, limit: int = 50
    ) -> list[GraphEdge]:
        await self.get_node(node_id)
        return await self.edge_repo.neighbors(
            node_id, relationship_type=relationship_type, limit=limit
        )

    async def subgraph(
        self,
        node_id: uuid.UUID,
        *,
        depth: int = 2,
        relationship_type: str | None = None,
    ) -> SubgraphResult:
        center = await self.get_node(node_id)
        bounded_depth = min(depth, MAX_TRAVERSAL_DEPTH)
        reachable = await self.edge_repo.reachable_node_ids(
            node_id, max_depth=bounded_depth, relationship_type=relationship_type
        )
        all_node_ids = [node_id, *reachable.keys()]
        nodes_by_id = await self.node_repo.list_by_ids(all_node_ids)
        nodes = [nodes_by_id[nid] for nid in all_node_ids if nid in nodes_by_id]

        edges: list[GraphEdge] = []
        seen_edge_ids: set[uuid.UUID] = set()
        node_id_set = set(all_node_ids)
        for nid in all_node_ids:
            touching = await self.edge_repo.list_edges(
                relationship_type=relationship_type, node_id=nid, limit=500
            )
            for edge in touching:
                if edge.id in seen_edge_ids:
                    continue
                if edge.source_node_id in node_id_set and edge.target_node_id in node_id_set:
                    seen_edge_ids.add(edge.id)
                    edges.append(edge)

        return SubgraphResult(center=center, nodes=nodes, edges=edges)

    async def shortest_path(
        self,
        source_canonical_id: str,
        target_canonical_id: str,
        *,
        max_depth: int = MAX_TRAVERSAL_DEPTH,
        relationship_type: str | None = None,
    ) -> PathResult | None:
        source = await self.get_node_by_canonical_id(source_canonical_id)
        target = await self.get_node_by_canonical_id(target_canonical_id)
        bounded_depth = min(max_depth, MAX_TRAVERSAL_DEPTH)

        path_node_ids = await self.edge_repo.shortest_path_node_ids(
            source.id, target.id, max_depth=bounded_depth, relationship_type=relationship_type
        )
        if path_node_ids is None:
            return None

        nodes_by_id = await self.node_repo.list_by_ids(path_node_ids)
        nodes = [nodes_by_id[nid] for nid in path_node_ids if nid in nodes_by_id]

        edges: list[GraphEdge] = []
        # Deliberately strict=False: path_node_ids[1:] is always one
        # shorter than path_node_ids - this is the standard pairwise
        # ("each node with its successor") idiom, not a length mismatch.
        for left_id, right_id in zip(path_node_ids, path_node_ids[1:], strict=False):
            touching = await self.edge_repo.list_edges(
                relationship_type=relationship_type, node_id=left_id, limit=500
            )
            hop_edges = [
                e for e in touching if {e.source_node_id, e.target_node_id} == {left_id, right_id}
            ]
            if hop_edges:
                edges.append(max(hop_edges, key=lambda e: e.confidence))

        return PathResult(nodes=nodes, edges=edges)

    # -- merge -------------------------------------------------------------

    async def merge_nodes(
        self, source_node_id: uuid.UUID, target_node_id: uuid.UUID, *, requested_by: uuid.UUID
    ) -> GraphNode:
        if source_node_id == target_node_id:
            raise ConflictError("Cannot merge a graph node into itself")

        source = await self.get_node(source_node_id)
        target = await self.get_node(target_node_id)
        target = await self.node_repo.resolve_active_node(target)
        if source.id == target.id:
            raise ConflictError("Source and target already resolve to the same graph node")
        if source.status == GraphNodeStatus.MERGED:
            raise ConflictError(f"Graph node {source_node_id} is already merged")

        edges = await self.edge_repo.list_for_node(source.id)
        for edge in edges:
            new_source_id = target.id if edge.source_node_id == source.id else edge.source_node_id
            new_target_id = target.id if edge.target_node_id == source.id else edge.target_node_id
            if new_source_id == new_target_id:
                # Would become a self-loop after the merge - not a
                # relationship that can exist in this ontology, drop it
                # rather than persist something meaningless.
                await self.evidence_repo.delete_for_edges([edge.id])
                await self.edge_repo.delete(edge)
                continue

            survivor_edge = await self.edge_repo.get_by_triple(
                new_source_id, new_target_id, edge.relationship_type
            )
            if survivor_edge is not None and survivor_edge.id != edge.id:
                evidence_rows = await self.evidence_repo.list_for_edge(edge.id)
                for row in evidence_rows:
                    await self.evidence_repo.update(row, edge_id=survivor_edge.id)
                merged_confidence = max(survivor_edge.confidence, edge.confidence)
                new_count = await self.evidence_repo.count_distinct_chunks_for_edge(
                    survivor_edge.id
                )
                await self.edge_repo.update(
                    survivor_edge, confidence=merged_confidence, evidence_count=new_count
                )
                await self.edge_repo.delete(edge)
            else:
                await self.edge_repo.update(
                    edge, source_node_id=new_source_id, target_node_id=new_target_id
                )

        merged_aliases = sorted(
            set(target.aliases_json) | set(source.aliases_json) | {source.display_name}
        )
        await self.node_repo.update(target, aliases_json=merged_aliases)
        await self.node_repo.update(source, status=GraphNodeStatus.MERGED, merged_into_id=target.id)

        await self.audit_service.record(
            user_id=requested_by,
            action="graph.nodes_merged",
            resource_type="graph_node",
            resource_id=target.id,
            metadata={"source_node_id": str(source.id), "target_node_id": str(target.id)},
        )
        return target
