"""REFERENCES (contract -> commodity).

Unlike the other rules, this one needs no connecting verb phrase:
a contract is, by nature, about whatever commodity terms surround it in
the same chunk. Short proximity (bounded by connector_text's max_gap,
same bound every other rule uses) is itself the evidence -
evidence_type="co_occurrence", and correspondingly the weakest base
confidence of any rule in this registry, since "mentioned nearby" is a
strictly weaker claim than an explicit verb phrase.
"""

from app.modules.extraction.models import EntityType
from app.modules.graph.domain import connector_text
from app.modules.graph.rules.types import RelationshipCandidate, RelationshipFinding


class ContractReferencesCommodityRule:
    rule_id = "relationship.contract_references_commodity"
    relationship_type = "references"
    applicable_type_pairs = frozenset({frozenset({EntityType.CONTRACT, EntityType.COMMODITY})})
    base_confidence = 0.55

    def evaluate(self, candidate: RelationshipCandidate) -> RelationshipFinding | None:
        left, right = candidate.pair.left_entity, candidate.pair.right_entity
        if connector_text(candidate.chunk_text, candidate.pair) is None:
            return None
        if left.entity_type == EntityType.CONTRACT and right.entity_type == EntityType.COMMODITY:
            contract_entity, commodity_entity = left, right
        elif left.entity_type == EntityType.COMMODITY and right.entity_type == EntityType.CONTRACT:
            contract_entity, commodity_entity = right, left
        else:
            return None
        return RelationshipFinding(
            relationship_type=self.relationship_type,
            source_entity_id=contract_entity.id,
            target_entity_id=commodity_entity.id,
            base_confidence=self.base_confidence,
            evidence_type="co_occurrence",
            matched_text=None,
        )
