"""Output types for the graph build pipeline's three agents. Frozen
dataclasses, not Pydantic, same reasoning as trust/agents/schemas.py:
nothing here validates untrusted LLM output, these are internal
handoffs between deterministic computation steps on the blackboard
(AgentContext.state) - see pipeline.py.
"""

import uuid
from dataclasses import dataclass

from app.modules.extraction.models import ExtractedEntity
from app.modules.graph.models import GraphNodeStatus


@dataclass(frozen=True, slots=True)
class NodeUpsertPlan:
    """One row per unique canonical_id observed among this run's
    eligible entities. node_id is pre-generated (client-side uuid4, same
    trick GraphNode.id's own column default uses) so
    RelationshipExtractionAgent can reference it before
    PersistGraphResultsAgent has actually written the row."""

    node_id: uuid.UUID
    canonical_id: str
    node_type: str
    display_name: str
    is_new: bool
    existing_status: GraphNodeStatus | None
    new_aliases: frozenset[str]


@dataclass(frozen=True, slots=True)
class EligibleEntity:
    """A node-eligible entity that resolved to a canonical_id and has a
    trust-pipeline confidence score - the population
    RelationshipExtractionAgent draws candidate pairs from."""

    entity: ExtractedEntity
    node_id: uuid.UUID
    canonical_id: str
    overall_confidence: float


@dataclass(frozen=True, slots=True)
class NodeResolutionOutput:
    node_plans: list[NodeUpsertPlan]
    eligible_entities: list[EligibleEntity]
    entities_skipped_ineligible_type: int
    entities_skipped_unresolved: int
    entities_skipped_no_confidence: int


@dataclass(frozen=True, slots=True)
class ResolvedFinding:
    """A RelationshipFinding (see rules/types.py) resolved to graph node
    ids and combined confidence, plus the provenance needed to write its
    GraphEvidence rows."""

    relationship_type: str
    source_node_id: uuid.UUID
    target_node_id: uuid.UUID
    confidence: float
    evidence_type: str
    matched_text: str | None
    source_entity_id: uuid.UUID
    target_entity_id: uuid.UUID
    document_id: uuid.UUID
    extraction_run_id: uuid.UUID
    chunk_id: uuid.UUID
    source_page_number: int | None
    target_page_number: int | None
    prompt_hash: str


@dataclass(frozen=True, slots=True)
class RelationshipExtractionOutput:
    findings: list[ResolvedFinding]
    candidate_pairs_evaluated: int
    discarded_low_confidence: int


@dataclass(frozen=True, slots=True)
class PersistGraphResultsOutput:
    nodes_created: int
    nodes_updated: int
    edges_created: int
    edges_updated: int
    evidence_created: int
