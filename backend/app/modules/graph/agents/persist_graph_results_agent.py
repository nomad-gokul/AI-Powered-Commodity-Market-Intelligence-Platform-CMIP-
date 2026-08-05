"""PersistGraphResultsAgent: the pipeline's only step that writes to the
database - same "only Persist writes" separation trust/agents/ uses.
Upserts nodes, upserts edges (folding new evidence into an existing
edge's confidence/evidence_count rather than duplicating it), and writes
the itemized GraphEvidence trail, deduplicated against what's already
recorded so re-running a build on unchanged data is a true no-op.
"""

import uuid
from typing import Any

from shared.agent_contracts import AgentContext

from app.modules.graph.agents.schemas import (
    NodeResolutionOutput,
    PersistGraphResultsOutput,
    RelationshipExtractionOutput,
    ResolvedFinding,
)
from app.modules.graph.models import GraphEdge, GraphEvidence, GraphNode, GraphNodeStatus
from app.modules.graph.repository import (
    GraphEdgeRepository,
    GraphEvidenceRepository,
    GraphNodeRepository,
)


def _provenance(finding: ResolvedFinding) -> dict[str, Any]:
    return {
        "latest_document_id": str(finding.document_id),
        "latest_extraction_run_id": str(finding.extraction_run_id),
        "latest_evidence_type": finding.evidence_type,
    }


class PersistGraphResultsAgent:
    def __init__(
        self,
        *,
        node_repo: GraphNodeRepository,
        edge_repo: GraphEdgeRepository,
        evidence_repo: GraphEvidenceRepository,
    ) -> None:
        self._node_repo = node_repo
        self._edge_repo = edge_repo
        self._evidence_repo = evidence_repo

    @property
    def name(self) -> str:
        return "persist_graph_results"

    async def run(self, context: AgentContext) -> PersistGraphResultsOutput:
        node_output: NodeResolutionOutput = context.state["node_resolution"]
        relationship_output: RelationshipExtractionOutput = context.state["relationship_extraction"]

        nodes_created, nodes_updated = await self._persist_nodes(node_output)
        edges_created, edges_updated, evidence_created = await self._persist_relationships(
            relationship_output
        )

        return PersistGraphResultsOutput(
            nodes_created=nodes_created,
            nodes_updated=nodes_updated,
            edges_created=edges_created,
            edges_updated=edges_updated,
            evidence_created=evidence_created,
        )

    async def _persist_nodes(self, node_output: NodeResolutionOutput) -> tuple[int, int]:
        nodes_created = 0
        nodes_updated = 0
        for plan in node_output.node_plans:
            if plan.is_new:
                await self._node_repo.create(
                    GraphNode(
                        id=plan.node_id,
                        canonical_id=plan.canonical_id,
                        node_type=plan.node_type,
                        display_name=plan.display_name,
                        aliases_json=sorted(plan.new_aliases),
                        status=GraphNodeStatus.ACTIVE,
                    )
                )
                nodes_created += 1
            elif plan.new_aliases:
                existing = await self._node_repo.get_by_id(plan.node_id)
                assert existing is not None
                merged = sorted(set(existing.aliases_json) | plan.new_aliases)
                if merged != existing.aliases_json:
                    await self._node_repo.update(existing, aliases_json=merged)
                    nodes_updated += 1
        return nodes_created, nodes_updated

    async def _persist_relationships(
        self, relationship_output: RelationshipExtractionOutput
    ) -> tuple[int, int, int]:
        edge_cache: dict[tuple[uuid.UUID, uuid.UUID, str], GraphEdge] = {}
        newly_created_edge_ids: set[uuid.UUID] = set()
        edge_by_finding: list[tuple[ResolvedFinding, GraphEdge]] = []

        for finding in relationship_output.findings:
            key = (finding.source_node_id, finding.target_node_id, finding.relationship_type)
            edge = edge_cache.get(key)
            if edge is None:
                edge = await self._edge_repo.get_by_triple(*key)
            if edge is None:
                edge = await self._edge_repo.create(
                    GraphEdge(
                        source_node_id=finding.source_node_id,
                        target_node_id=finding.target_node_id,
                        relationship_type=finding.relationship_type,
                        confidence=finding.confidence,
                        evidence_count=0,
                        provenance_json=_provenance(finding),
                    )
                )
                newly_created_edge_ids.add(edge.id)
            else:
                new_confidence = max(edge.confidence, finding.confidence)
                edge = await self._edge_repo.update(
                    edge, confidence=new_confidence, provenance_json=_provenance(finding)
                )
            edge_cache[key] = edge
            edge_by_finding.append((finding, edge))

        evidence_created = await self._persist_evidence(edge_by_finding)

        touched_edge_ids = {edge.id for _, edge in edge_by_finding}
        for edge_id in touched_edge_ids:
            count = await self._evidence_repo.count_distinct_chunks_for_edge(edge_id)
            edge = next(e for _, e in edge_by_finding if e.id == edge_id)
            if edge.evidence_count != count:
                await self._edge_repo.update(edge, evidence_count=count)

        edges_updated = len(touched_edge_ids - newly_created_edge_ids)
        return len(newly_created_edge_ids), edges_updated, evidence_created

    async def _persist_evidence(
        self, edge_by_finding: list[tuple[ResolvedFinding, GraphEdge]]
    ) -> int:
        touched_edge_ids = list({edge.id for _, edge in edge_by_finding})
        seen_keys = await self._evidence_repo.existing_keys_for_edges(touched_edge_ids)

        new_evidence: list[GraphEvidence] = []
        for finding, edge in edge_by_finding:
            for entity_id, page_number in (
                (finding.source_entity_id, finding.source_page_number),
                (finding.target_entity_id, finding.target_page_number),
            ):
                evidence_key = (edge.id, entity_id, finding.chunk_id)
                if evidence_key in seen_keys:
                    continue
                seen_keys.add(evidence_key)
                new_evidence.append(
                    GraphEvidence(
                        edge_id=edge.id,
                        document_id=finding.document_id,
                        extraction_run_id=finding.extraction_run_id,
                        entity_id=entity_id,
                        page_number=page_number,
                        chunk_id=finding.chunk_id,
                        prompt_hash=finding.prompt_hash,
                    )
                )
        if new_evidence:
            await self._evidence_repo.bulk_create(new_evidence)
        return len(new_evidence)
