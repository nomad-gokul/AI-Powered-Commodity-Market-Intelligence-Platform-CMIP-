"""NodeResolutionAgent: decides which of an extraction run's entities are
eligible to become (or update) a graph node, and pre-computes the node id
each will resolve to - so RelationshipExtractionAgent can build edges
referencing those ids before PersistGraphResultsAgent has actually
written the rows (a node's id is a client-side uuid4, same trick
GraphNode.id's own column default uses, so this is safe: whichever agent
writes the row last will write it with this exact id).

Never writes to the database - purely reads via the repositories it's
given, same "only Persist writes" separation trust/agents/ established.
"""

import uuid

from app.ai.engine.types import AgentContext
from app.modules.extraction.models import ExtractedEntity
from app.modules.extraction.repository import ExtractedEntityRepository
from app.modules.extraction.trust.repository import (
    ConfidenceScoreRepository,
    NormalizationResultRepository,
)
from app.modules.graph.agents.schemas import EligibleEntity, NodeResolutionOutput, NodeUpsertPlan
from app.modules.graph.domain import GRAPH_NODE_ELIGIBLE_TYPES
from app.modules.graph.repository import GraphNodeRepository


class NodeResolutionAgent:
    def __init__(
        self,
        *,
        extraction_run_id: uuid.UUID,
        entity_repo: ExtractedEntityRepository,
        normalization_repo: NormalizationResultRepository,
        confidence_repo: ConfidenceScoreRepository,
        node_repo: GraphNodeRepository,
    ) -> None:
        self._extraction_run_id = extraction_run_id
        self._entity_repo = entity_repo
        self._normalization_repo = normalization_repo
        self._confidence_repo = confidence_repo
        self._node_repo = node_repo

    @property
    def name(self) -> str:
        return "node_resolution"

    async def run(self, context: AgentContext) -> NodeResolutionOutput:
        entities = await self._entity_repo.list_all_for_run(self._extraction_run_id)
        eligible_type_entities = [e for e in entities if e.entity_type in GRAPH_NODE_ELIGIBLE_TYPES]
        skipped_ineligible_type = len(entities) - len(eligible_type_entities)

        entity_ids = [e.id for e in eligible_type_entities]
        norm_map = await self._normalization_repo.list_for_entities(entity_ids)
        conf_map = await self._confidence_repo.list_for_entities(entity_ids)

        skipped_unresolved = 0
        skipped_no_confidence = 0
        resolvable: list[tuple[ExtractedEntity, str, float]] = []
        for entity in eligible_type_entities:
            normalization = norm_map.get(entity.id)
            if normalization is None or normalization.canonical_id is None:
                skipped_unresolved += 1
                continue
            confidence = conf_map.get(entity.id)
            if confidence is None:
                skipped_no_confidence += 1
                continue
            resolvable.append((entity, normalization.canonical_id, confidence.overall_score))

        node_plans: dict[str, NodeUpsertPlan] = {}
        eligible_entities: list[EligibleEntity] = []
        for entity, canonical_id, overall_confidence in resolvable:
            plan = node_plans.get(canonical_id)
            if plan is None:
                existing = await self._node_repo.get_by_canonical_id(canonical_id)
                if existing is None:
                    plan = NodeUpsertPlan(
                        node_id=uuid.uuid4(),
                        canonical_id=canonical_id,
                        node_type=entity.entity_type.value,
                        display_name=entity.normalized_value or entity.raw_value,
                        is_new=True,
                        existing_status=None,
                        new_aliases=frozenset({entity.raw_value}),
                    )
                else:
                    resolved = await self._node_repo.resolve_active_node(existing)
                    new_alias = (
                        frozenset({entity.raw_value})
                        if entity.raw_value not in resolved.aliases_json
                        else frozenset()
                    )
                    plan = NodeUpsertPlan(
                        node_id=resolved.id,
                        canonical_id=canonical_id,
                        node_type=resolved.node_type,
                        display_name=resolved.display_name,
                        is_new=False,
                        existing_status=resolved.status,
                        new_aliases=new_alias,
                    )
                node_plans[canonical_id] = plan
            elif entity.raw_value not in plan.new_aliases:
                node_plans[canonical_id] = NodeUpsertPlan(
                    node_id=plan.node_id,
                    canonical_id=plan.canonical_id,
                    node_type=plan.node_type,
                    display_name=plan.display_name,
                    is_new=plan.is_new,
                    existing_status=plan.existing_status,
                    new_aliases=plan.new_aliases | {entity.raw_value},
                )
                plan = node_plans[canonical_id]

            eligible_entities.append(
                EligibleEntity(
                    entity=entity,
                    node_id=plan.node_id,
                    canonical_id=canonical_id,
                    overall_confidence=overall_confidence,
                )
            )

        return NodeResolutionOutput(
            node_plans=list(node_plans.values()),
            eligible_entities=eligible_entities,
            entities_skipped_ineligible_type=skipped_ineligible_type,
            entities_skipped_unresolved=skipped_unresolved,
            entities_skipped_no_confidence=skipped_no_confidence,
        )
