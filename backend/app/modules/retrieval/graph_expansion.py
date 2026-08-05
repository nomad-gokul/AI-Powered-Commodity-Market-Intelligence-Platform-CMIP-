"""GraphExpansion: expands a set of seed canonical entity IDs into related
graph nodes and edges.

A thin wrapper around Phase 4's KnowledgeGraphService.subgraph() - the
recursive-CTE traversal itself is never reimplemented here, only called
(see docs/ARCHITECTURE.md's Phase 5 section). Hop distance per node (used
by RerankerService's graph_distance signal) isn't returned by
SubgraphResult, so it's derived locally via a cheap BFS over the already-
fetched, already depth-bounded edge list - deriving a value from an
in-memory result set is not the same thing as reimplementing the SQL
traversal that produced it.
"""

import time
import uuid
from collections import deque
from dataclasses import dataclass

from app.core.exceptions import NotFoundError
from app.core.metrics import graph_expansion_duration_seconds
from app.modules.graph.models import GraphEdge, GraphNode
from app.modules.graph.query_service import KnowledgeGraphService, SubgraphResult


@dataclass(frozen=True, slots=True)
class GraphExpansionHit:
    node: GraphNode
    hop_distance: int
    seed_canonical_id: str


@dataclass(frozen=True, slots=True)
class GraphExpansionResult:
    nodes: list[GraphExpansionHit]
    edges: list[GraphEdge]


class GraphExpansion:
    def __init__(self, graph_service: KnowledgeGraphService) -> None:
        self._graph_service = graph_service

    async def expand(
        self,
        seed_canonical_ids: list[str],
        *,
        depth: int = 2,
        relationship_type: str | None = None,
    ) -> GraphExpansionResult:
        """Unresolvable seeds (no matching graph node - e.g. an entity
        QueryAnalyzer detected in text but that was never canonicalized
        into the graph) are skipped, not an error: partial expansion from
        the seeds that DO resolve is still useful context."""
        started = time.monotonic()
        nodes_by_id: dict[uuid.UUID, GraphExpansionHit] = {}
        edges_by_id: dict[uuid.UUID, GraphEdge] = {}

        for canonical_id in seed_canonical_ids:
            try:
                seed = await self._graph_service.get_node_by_canonical_id(canonical_id)
            except NotFoundError:
                continue
            result = await self._graph_service.subgraph(
                seed.id, depth=depth, relationship_type=relationship_type
            )
            hop_by_node_id = self._hop_distances(seed.id, result)
            for node in result.nodes:
                hop = hop_by_node_id.get(node.id, 0)
                existing = nodes_by_id.get(node.id)
                if existing is None or hop < existing.hop_distance:
                    nodes_by_id[node.id] = GraphExpansionHit(
                        node=node, hop_distance=hop, seed_canonical_id=canonical_id
                    )
            for edge in result.edges:
                edges_by_id[edge.id] = edge

        graph_expansion_duration_seconds.observe(time.monotonic() - started)
        return GraphExpansionResult(
            nodes=list(nodes_by_id.values()), edges=list(edges_by_id.values())
        )

    @staticmethod
    def _hop_distances(seed_id: uuid.UUID, result: SubgraphResult) -> dict[uuid.UUID, int]:
        adjacency: dict[uuid.UUID, list[uuid.UUID]] = {}
        for edge in result.edges:
            adjacency.setdefault(edge.source_node_id, []).append(edge.target_node_id)
            adjacency.setdefault(edge.target_node_id, []).append(edge.source_node_id)

        distances: dict[uuid.UUID, int] = {seed_id: 0}
        queue: deque[uuid.UUID] = deque([seed_id])
        while queue:
            current = queue.popleft()
            for neighbor in adjacency.get(current, []):
                if neighbor not in distances:
                    distances[neighbor] = distances[current] + 1
                    queue.append(neighbor)
        return distances
