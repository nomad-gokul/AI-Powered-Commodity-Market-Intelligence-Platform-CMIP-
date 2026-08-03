"""Builds the SequentialEngine pipeline for one graph-build pass over a
single extraction run's trusted entities:

Node Resolution -> Relationship Extraction -> Persist

Every step is deterministic (no LLM call) so every step gets the same
generous retry policy, same reasoning as trust/pipeline.py.
GraphBuilderService.build_all runs this pipeline once per extraction run
in the corpus (see builder_service.py) - the pipeline itself is always
scoped to one run.
"""

import uuid

from app.ai.engine.base import EngineStep
from app.ai.engine.types import RetryPolicy
from app.modules.documents.repository import DocumentChunkRepository
from app.modules.extraction.repository import (
    EntityMentionRepository,
    ExtractedEntityRepository,
    ExtractionRunRepository,
)
from app.modules.extraction.trust.repository import (
    ConfidenceScoreRepository,
    NormalizationResultRepository,
)
from app.modules.graph.agents.node_resolution_agent import NodeResolutionAgent
from app.modules.graph.agents.persist_graph_results_agent import PersistGraphResultsAgent
from app.modules.graph.agents.relationship_extraction_agent import RelationshipExtractionAgent
from app.modules.graph.repository import (
    GraphEdgeRepository,
    GraphEvidenceRepository,
    GraphNodeRepository,
)
from app.modules.graph.rules.registry import RelationshipRuleRegistry

_RETRY_POLICY = RetryPolicy(max_attempts=2, backoff_base_seconds=1.0, backoff_multiplier=2.0)
_STEP_TIMEOUT_SECONDS = 120.0


def build_graph_pipeline(
    *,
    extraction_run_id: uuid.UUID,
    entity_repo: ExtractedEntityRepository,
    mention_repo: EntityMentionRepository,
    chunk_repo: DocumentChunkRepository,
    extraction_run_repo: ExtractionRunRepository,
    normalization_repo: NormalizationResultRepository,
    confidence_repo: ConfidenceScoreRepository,
    node_repo: GraphNodeRepository,
    edge_repo: GraphEdgeRepository,
    evidence_repo: GraphEvidenceRepository,
    rule_registry: RelationshipRuleRegistry,
) -> list[EngineStep]:
    node_resolution = NodeResolutionAgent(
        extraction_run_id=extraction_run_id,
        entity_repo=entity_repo,
        normalization_repo=normalization_repo,
        confidence_repo=confidence_repo,
        node_repo=node_repo,
    )
    relationship_extraction = RelationshipExtractionAgent(
        extraction_run_id=extraction_run_id,
        mention_repo=mention_repo,
        chunk_repo=chunk_repo,
        extraction_run_repo=extraction_run_repo,
        rule_registry=rule_registry,
    )
    persist = PersistGraphResultsAgent(
        node_repo=node_repo, edge_repo=edge_repo, evidence_repo=evidence_repo
    )

    return [
        EngineStep(agent=agent, retry_policy=_RETRY_POLICY, timeout_seconds=_STEP_TIMEOUT_SECONDS)
        for agent in (node_resolution, relationship_extraction, persist)
    ]
