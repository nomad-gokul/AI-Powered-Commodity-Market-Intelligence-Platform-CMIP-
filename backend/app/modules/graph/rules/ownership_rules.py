"""OWNS (company -> port) and OPERATES (company -> terminal).

Each rule only fires when the two entities' types AND the connector's
grammatical direction both match the relationship being claimed - e.g.
"Port owns Company" (a real but nonsensical reversal) is declined rather
than silently flipped, since flipping it would assert something the text
never actually said.
"""

import re

from app.modules.extraction.models import EntityType
from app.modules.graph.domain import connector_text
from app.modules.graph.rules.types import RelationshipCandidate, RelationshipFinding

_OWNS_FORWARD = re.compile(r"\bowns?\b|\bowning\b", re.IGNORECASE)
_OWNS_BACKWARD = re.compile(r"\bowned\s+by\b", re.IGNORECASE)

_OPERATES_FORWARD = re.compile(r"\boperates?\b|\boperating\b", re.IGNORECASE)
_OPERATES_BACKWARD = re.compile(r"\boperated\s+by\b", re.IGNORECASE)


class CompanyOwnsPortRule:
    rule_id = "relationship.company_owns_port"
    relationship_type = "owns"
    applicable_type_pairs = frozenset({frozenset({EntityType.COMPANY, EntityType.PORT})})
    base_confidence = 0.75

    def evaluate(self, candidate: RelationshipCandidate) -> RelationshipFinding | None:
        left, right = candidate.pair.left_entity, candidate.pair.right_entity
        connector = connector_text(candidate.chunk_text, candidate.pair)
        if connector is None:
            return None
        if left.entity_type == EntityType.COMPANY and right.entity_type == EntityType.PORT:
            if _OWNS_FORWARD.search(connector):
                return RelationshipFinding(
                    relationship_type=self.relationship_type,
                    source_entity_id=left.id,
                    target_entity_id=right.id,
                    base_confidence=self.base_confidence,
                    evidence_type="text_pattern",
                    matched_text=connector.strip(),
                )
            return None
        if left.entity_type == EntityType.PORT and right.entity_type == EntityType.COMPANY:
            if _OWNS_BACKWARD.search(connector):
                return RelationshipFinding(
                    relationship_type=self.relationship_type,
                    source_entity_id=right.id,
                    target_entity_id=left.id,
                    base_confidence=self.base_confidence,
                    evidence_type="text_pattern",
                    matched_text=connector.strip(),
                )
        return None


class CompanyOperatesTerminalRule:
    rule_id = "relationship.company_operates_terminal"
    relationship_type = "operates"
    applicable_type_pairs = frozenset({frozenset({EntityType.COMPANY, EntityType.TERMINAL})})
    base_confidence = 0.75

    def evaluate(self, candidate: RelationshipCandidate) -> RelationshipFinding | None:
        left, right = candidate.pair.left_entity, candidate.pair.right_entity
        connector = connector_text(candidate.chunk_text, candidate.pair)
        if connector is None:
            return None
        if left.entity_type == EntityType.COMPANY and right.entity_type == EntityType.TERMINAL:
            if _OPERATES_FORWARD.search(connector):
                return RelationshipFinding(
                    relationship_type=self.relationship_type,
                    source_entity_id=left.id,
                    target_entity_id=right.id,
                    base_confidence=self.base_confidence,
                    evidence_type="text_pattern",
                    matched_text=connector.strip(),
                )
            return None
        if left.entity_type == EntityType.TERMINAL and right.entity_type == EntityType.COMPANY:
            if _OPERATES_BACKWARD.search(connector):
                return RelationshipFinding(
                    relationship_type=self.relationship_type,
                    source_entity_id=right.id,
                    target_entity_id=left.id,
                    base_confidence=self.base_confidence,
                    evidence_type="text_pattern",
                    matched_text=connector.strip(),
                )
        return None
