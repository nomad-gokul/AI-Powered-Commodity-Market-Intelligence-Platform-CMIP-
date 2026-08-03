"""RelationshipExtractionAgent: evaluates every applicable relationship
rule against every pair of node-eligible entities that co-occur in the
same document chunk, and resolves survivors to graph node ids and a
combined confidence.

Reads NodeResolutionAgent's output off the blackboard
(context.state["node_resolution"]) for the entity_id -> node_id mapping
and each entity's overall confidence - never writes to the database.
"""

import itertools
import uuid
from collections import defaultdict

from app.ai.engine.types import AgentContext
from app.modules.documents.repository import DocumentChunkRepository
from app.modules.extraction.models import EntityMention, ExtractedEntity
from app.modules.extraction.repository import EntityMentionRepository, ExtractionRunRepository
from app.modules.graph.agents.schemas import (
    EligibleEntity,
    NodeResolutionOutput,
    RelationshipExtractionOutput,
    ResolvedFinding,
)
from app.modules.graph.domain import (
    MIN_EDGE_CONFIDENCE,
    combine_edge_confidence,
    order_mentions_by_offset,
)
from app.modules.graph.rules.registry import RelationshipRuleRegistry
from app.modules.graph.rules.types import RelationshipCandidate


class RelationshipExtractionAgent:
    def __init__(
        self,
        *,
        extraction_run_id: uuid.UUID,
        mention_repo: EntityMentionRepository,
        chunk_repo: DocumentChunkRepository,
        extraction_run_repo: ExtractionRunRepository,
        rule_registry: RelationshipRuleRegistry,
    ) -> None:
        self._extraction_run_id = extraction_run_id
        self._mention_repo = mention_repo
        self._chunk_repo = chunk_repo
        self._extraction_run_repo = extraction_run_repo
        self._rule_registry = rule_registry

    @property
    def name(self) -> str:
        return "relationship_extraction"

    async def run(self, context: AgentContext) -> RelationshipExtractionOutput:
        node_output: NodeResolutionOutput = context.state["node_resolution"]
        eligible_entities = node_output.eligible_entities
        if not eligible_entities:
            return RelationshipExtractionOutput(
                findings=[], candidate_pairs_evaluated=0, discarded_low_confidence=0
            )

        extraction_run = await self._extraction_run_repo.get_by_id(self._extraction_run_id)
        assert extraction_run is not None  # guaranteed by the caller's own status check

        mentions_map = await self._mention_repo.list_for_entities(
            [ee.entity.id for ee in eligible_entities]
        )

        by_chunk: dict[uuid.UUID, list[tuple[EligibleEntity, EntityMention]]] = defaultdict(list)
        for ee in eligible_entities:
            entity: ExtractedEntity = ee.entity
            if entity.source_chunk is None:
                continue
            mentions = mentions_map.get(entity.id, [])
            if not mentions:
                continue
            by_chunk[entity.source_chunk].append((ee, mentions[0]))

        chunks_map = await self._chunk_repo.list_by_ids(list(by_chunk.keys()))

        findings: list[ResolvedFinding] = []
        candidate_pairs_evaluated = 0
        discarded_low_confidence = 0

        for chunk_id, chunk_entities in by_chunk.items():
            chunk = chunks_map.get(chunk_id)
            if chunk is None:
                continue
            for (ee_a, mention_a), (ee_b, mention_b) in itertools.combinations(chunk_entities, 2):
                ordered = order_mentions_by_offset(ee_a.entity, mention_a, ee_b.entity, mention_b)
                if ordered is None:
                    continue
                candidate_pairs_evaluated += 1
                candidate = RelationshipCandidate(pair=ordered, chunk_text=chunk.text)
                rules = self._rule_registry.rules_for_type_pair(
                    ee_a.entity.entity_type, ee_b.entity.entity_type
                )
                for rule in rules:
                    finding = rule.evaluate(candidate)
                    if finding is None:
                        continue
                    source_ee = ee_a if finding.source_entity_id == ee_a.entity.id else ee_b
                    target_ee = ee_a if finding.target_entity_id == ee_a.entity.id else ee_b
                    confidence = combine_edge_confidence(
                        finding.base_confidence,
                        source_ee.overall_confidence,
                        target_ee.overall_confidence,
                    )
                    if confidence < MIN_EDGE_CONFIDENCE:
                        discarded_low_confidence += 1
                        continue
                    findings.append(
                        ResolvedFinding(
                            relationship_type=finding.relationship_type,
                            source_node_id=source_ee.node_id,
                            target_node_id=target_ee.node_id,
                            confidence=confidence,
                            evidence_type=finding.evidence_type,
                            matched_text=finding.matched_text,
                            source_entity_id=source_ee.entity.id,
                            target_entity_id=target_ee.entity.id,
                            document_id=extraction_run.document_id,
                            extraction_run_id=self._extraction_run_id,
                            chunk_id=chunk_id,
                            source_page_number=mention_a.page_number
                            if source_ee is ee_a
                            else mention_b.page_number,
                            target_page_number=mention_b.page_number
                            if target_ee is ee_b
                            else mention_a.page_number,
                            prompt_hash=extraction_run.prompt_hash,
                        )
                    )

        return RelationshipExtractionOutput(
            findings=findings,
            candidate_pairs_evaluated=candidate_pairs_evaluated,
            discarded_low_confidence=discarded_low_confidence,
        )
