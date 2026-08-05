"""GraphBuilderService: the class the Phase 4 spec names directly, with
exactly its stated responsibilities - create nodes, merge aliases,
create edges, attach provenance, avoid duplicate nodes/edges, maintain
evidence counts. Wraps build_graph_pipeline()'s three-step
SequentialEngine run (see pipeline.py) for a single extraction run, and
build_all() for a full-corpus sweep across every extraction run with a
COMPLETED trust pipeline run.

Deliberately called BY the worker task rather than inlining pipeline
construction into app/worker/tasks.py the way trust/pipeline.py's
build_trust_pipeline is - the spec names this class explicitly, so its
build orchestration responsibility belongs here, not duplicated at the
call site. build_all() commits nothing itself; on a failure partway
through a full-corpus sweep, every extraction run processed before the
failure has already been validly upserted into the graph (the upsert
model has no notion of "undo run N because run N+3 failed") - the caller
persists that partial progress and records the run as FAILED with the
first error, since a retry only ever redoes the missing work (idempotent
rebuild, see pipeline.py/agents/persist_graph_results_agent.py).
"""

import uuid
from dataclasses import dataclass, replace

from ai_service.engine.sequential import SequentialEngine
from shared.agent_contracts import AgentContext

from app.core.exceptions import ConflictError
from app.modules.documents.repository import DocumentChunkRepository
from app.modules.extraction.models import ExtractionStatus
from app.modules.extraction.repository import (
    EntityMentionRepository,
    ExtractedEntityRepository,
    ExtractionRunRepository,
)
from app.modules.extraction.trust.repository import (
    ConfidenceScoreRepository,
    NormalizationResultRepository,
    TrustPipelineRunRepository,
)
from app.modules.graph.agents.schemas import PersistGraphResultsOutput
from app.modules.graph.pipeline import build_graph_pipeline
from app.modules.graph.repository import (
    GraphEdgeRepository,
    GraphEvidenceRepository,
    GraphNodeRepository,
)
from app.modules.graph.rules.registry import RelationshipRuleRegistry


class GraphBuildPartialFailure(Exception):
    """Raised by build_all when one extraction run in a full-corpus sweep
    fails - carries the stats accumulated from every run processed
    successfully before the failure, so the caller can record that
    partial progress on the GraphBuildRun row rather than reporting a
    completed sweep as having done nothing."""

    def __init__(
        self, stats: "GraphBuildStats", failed_extraction_run_id: uuid.UUID, message: str
    ) -> None:
        super().__init__(message)
        self.stats = stats
        self.failed_extraction_run_id = failed_extraction_run_id


@dataclass(frozen=True, slots=True)
class GraphBuildStats:
    runs_processed: int = 0
    nodes_created: int = 0
    nodes_updated: int = 0
    edges_created: int = 0
    edges_updated: int = 0
    evidence_created: int = 0

    def add(self, output: PersistGraphResultsOutput) -> "GraphBuildStats":
        return replace(
            self,
            runs_processed=self.runs_processed + 1,
            nodes_created=self.nodes_created + output.nodes_created,
            nodes_updated=self.nodes_updated + output.nodes_updated,
            edges_created=self.edges_created + output.edges_created,
            edges_updated=self.edges_updated + output.edges_updated,
            evidence_created=self.evidence_created + output.evidence_created,
        )


class GraphBuilderService:
    def __init__(
        self,
        *,
        entity_repo: ExtractedEntityRepository,
        mention_repo: EntityMentionRepository,
        chunk_repo: DocumentChunkRepository,
        extraction_run_repo: ExtractionRunRepository,
        normalization_repo: NormalizationResultRepository,
        confidence_repo: ConfidenceScoreRepository,
        node_repo: GraphNodeRepository,
        edge_repo: GraphEdgeRepository,
        evidence_repo: GraphEvidenceRepository,
        trust_run_repo: TrustPipelineRunRepository,
        rule_registry: RelationshipRuleRegistry,
    ) -> None:
        self.entity_repo = entity_repo
        self.mention_repo = mention_repo
        self.chunk_repo = chunk_repo
        self.extraction_run_repo = extraction_run_repo
        self.normalization_repo = normalization_repo
        self.confidence_repo = confidence_repo
        self.node_repo = node_repo
        self.edge_repo = edge_repo
        self.evidence_repo = evidence_repo
        self.trust_run_repo = trust_run_repo
        self.rule_registry = rule_registry

    async def build_for_extraction_run(
        self, extraction_run_id: uuid.UUID
    ) -> PersistGraphResultsOutput:
        trust_run = await self.trust_run_repo.latest_for_extraction_run(extraction_run_id)
        if trust_run is None or trust_run.status != ExtractionStatus.COMPLETED:
            raise ConflictError(
                f"Extraction run {extraction_run_id} has no COMPLETED trust pipeline run - "
                "it must be validated (POST /extraction-runs/{id}/validate) before it can "
                "contribute to the knowledge graph"
            )

        steps = build_graph_pipeline(
            extraction_run_id=extraction_run_id,
            entity_repo=self.entity_repo,
            mention_repo=self.mention_repo,
            chunk_repo=self.chunk_repo,
            extraction_run_repo=self.extraction_run_repo,
            normalization_repo=self.normalization_repo,
            confidence_repo=self.confidence_repo,
            node_repo=self.node_repo,
            edge_repo=self.edge_repo,
            evidence_repo=self.evidence_repo,
            rule_registry=self.rule_registry,
        )
        context = AgentContext(correlation_id=str(extraction_run_id))
        result = await SequentialEngine().run(steps, context)
        if not result.succeeded:
            error = next(
                (step.error for step in result.steps if step.error), "unknown graph build failure"
            )
            message = f"Graph build failed for extraction run {extraction_run_id}: {error}"
            raise RuntimeError(message)

        output: PersistGraphResultsOutput = result.output_of("persist_graph_results")
        return output

    async def build_all(self) -> GraphBuildStats:
        completed_trust_runs = await self.trust_run_repo.list_latest_completed()
        stats = GraphBuildStats()
        for trust_run in completed_trust_runs:
            try:
                output = await self.build_for_extraction_run(trust_run.extraction_run_id)
            except Exception as exc:
                failed_id = trust_run.extraction_run_id
                raise GraphBuildPartialFailure(stats, failed_id, str(exc)) from exc
            stats = stats.add(output)
        return stats
