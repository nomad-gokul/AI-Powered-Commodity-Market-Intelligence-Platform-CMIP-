"""LOCATED_IN (company -> country, port -> country).

Company/port location is stated two ways in market reports: a verb
phrase ("headquartered in", "located in") or bare adjacency ("Mundra,
India"). PortLocatedInCountryRule recognizes both - adjacency is weaker
evidence (evidence_type="adjacent_mention") and gets a lower base
confidence than an explicit verb phrase.
"""

import re

from app.modules.extraction.models import EntityType
from app.modules.graph.domain import connector_text
from app.modules.graph.rules.types import RelationshipCandidate, RelationshipFinding

_LOCATED_IN_PATTERN = re.compile(
    r"\bheadquartered\s+in\b|\bbased\s+in\b|\blocated\s+in\b|\bsituated\s+in\b|\bincorporated\s+in\b",
    re.IGNORECASE,
)
_ADJACENCY_PATTERN = re.compile(r"^\s*,\s*$")


class CompanyLocatedInCountryRule:
    rule_id = "relationship.company_located_in_country"
    relationship_type = "located_in"
    applicable_type_pairs = frozenset({frozenset({EntityType.COMPANY, EntityType.COUNTRY})})
    base_confidence = 0.70

    def evaluate(self, candidate: RelationshipCandidate) -> RelationshipFinding | None:
        left, right = candidate.pair.left_entity, candidate.pair.right_entity
        if left.entity_type != EntityType.COMPANY or right.entity_type != EntityType.COUNTRY:
            return None
        connector = connector_text(candidate.chunk_text, candidate.pair)
        if connector is None or not _LOCATED_IN_PATTERN.search(connector):
            return None
        return RelationshipFinding(
            relationship_type=self.relationship_type,
            source_entity_id=left.id,
            target_entity_id=right.id,
            base_confidence=self.base_confidence,
            evidence_type="text_pattern",
            matched_text=connector.strip(),
        )


class PortLocatedInCountryRule:
    rule_id = "relationship.port_located_in_country"
    relationship_type = "located_in"
    applicable_type_pairs = frozenset({frozenset({EntityType.PORT, EntityType.COUNTRY})})
    verb_base_confidence = 0.70
    adjacency_base_confidence = 0.60

    def evaluate(self, candidate: RelationshipCandidate) -> RelationshipFinding | None:
        left, right = candidate.pair.left_entity, candidate.pair.right_entity
        if left.entity_type != EntityType.PORT or right.entity_type != EntityType.COUNTRY:
            return None
        connector = connector_text(candidate.chunk_text, candidate.pair)
        if connector is None:
            return None
        if _LOCATED_IN_PATTERN.search(connector):
            return RelationshipFinding(
                relationship_type=self.relationship_type,
                source_entity_id=left.id,
                target_entity_id=right.id,
                base_confidence=self.verb_base_confidence,
                evidence_type="text_pattern",
                matched_text=connector.strip(),
            )
        if _ADJACENCY_PATTERN.match(connector):
            return RelationshipFinding(
                relationship_type=self.relationship_type,
                source_entity_id=left.id,
                target_entity_id=right.id,
                base_confidence=self.adjacency_base_confidence,
                evidence_type="adjacent_mention",
                matched_text=connector.strip() or None,
            )
        return None
