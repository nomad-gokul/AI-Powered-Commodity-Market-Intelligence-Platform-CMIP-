"""SHIPPED_FROM (commodity -> port) and SHIPPED_TO (commodity -> country).

Only the natural "Commodity shipped from Port" / "Commodity shipped to
Country" phrasing is recognized (commodity mentioned first) - a
passive-reversed construction ("Port received the Commodity") is rare
enough, and structurally ambiguous enough, that recognizing it would
risk false positives; left unrecognized rather than guessed.
"""

import re

from app.modules.extraction.models import EntityType
from app.modules.graph.domain import connector_text
from app.modules.graph.rules.types import RelationshipCandidate, RelationshipFinding

_SHIPPED_FROM_PATTERN = re.compile(
    r"\bshipped\s+from\b|\bloaded\s+at\b|\bdeparting\s+from\b|\bexported\s+from\b", re.IGNORECASE
)
_SHIPPED_TO_PATTERN = re.compile(
    r"\bshipped\s+to\b|\bdestined\s+for\b|\bbound\s+for\b|\bexported\s+to\b|\bimported\s+(?:in)?to\b",
    re.IGNORECASE,
)


class CommodityShippedFromPortRule:
    rule_id = "relationship.commodity_shipped_from_port"
    relationship_type = "shipped_from"
    applicable_type_pairs = frozenset({frozenset({EntityType.COMMODITY, EntityType.PORT})})
    base_confidence = 0.70

    def evaluate(self, candidate: RelationshipCandidate) -> RelationshipFinding | None:
        left, right = candidate.pair.left_entity, candidate.pair.right_entity
        if left.entity_type != EntityType.COMMODITY or right.entity_type != EntityType.PORT:
            return None
        connector = connector_text(candidate.chunk_text, candidate.pair)
        if connector is None or not _SHIPPED_FROM_PATTERN.search(connector):
            return None
        return RelationshipFinding(
            relationship_type=self.relationship_type,
            source_entity_id=left.id,
            target_entity_id=right.id,
            base_confidence=self.base_confidence,
            evidence_type="text_pattern",
            matched_text=connector.strip(),
        )


class CommodityShippedToCountryRule:
    rule_id = "relationship.commodity_shipped_to_country"
    relationship_type = "shipped_to"
    applicable_type_pairs = frozenset({frozenset({EntityType.COMMODITY, EntityType.COUNTRY})})
    base_confidence = 0.70

    def evaluate(self, candidate: RelationshipCandidate) -> RelationshipFinding | None:
        left, right = candidate.pair.left_entity, candidate.pair.right_entity
        if left.entity_type != EntityType.COMMODITY or right.entity_type != EntityType.COUNTRY:
            return None
        connector = connector_text(candidate.chunk_text, candidate.pair)
        if connector is None or not _SHIPPED_TO_PATTERN.search(connector):
            return None
        return RelationshipFinding(
            relationship_type=self.relationship_type,
            source_entity_id=left.id,
            target_entity_id=right.id,
            base_confidence=self.base_confidence,
            evidence_type="text_pattern",
            matched_text=connector.strip(),
        )
