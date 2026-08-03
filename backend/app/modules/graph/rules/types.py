"""Shared types for the relationship rule engine: the candidate a rule
evaluates, the finding it may produce, and the Protocol every rule
implements. Mirrors trust/rules/types.py's shape (EntityValidationRule /
ValidationFinding) for the same reason: a configurable rule registry,
not a hardcoded if/elif chain, so a future custom relationship rule is
additive.
"""

import uuid
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from app.modules.extraction.models import EntityType
from app.modules.graph.domain import OrderedMentionPair


@dataclass(frozen=True, slots=True)
class RelationshipCandidate:
    """Two entities co-occurring in the same document chunk, ordered by
    where they appear, plus the full chunk text a rule may slice for a
    connecting phrase."""

    pair: OrderedMentionPair
    chunk_text: str


@dataclass(frozen=True, slots=True)
class RelationshipFinding:
    """A rule's verdict: a specific relationship_type holds from
    source_entity_id to target_entity_id, with a base_confidence the
    builder will scale by the two entities' own trust scores - see
    domain.combine_edge_confidence.
    """

    relationship_type: str
    source_entity_id: uuid.UUID
    target_entity_id: uuid.UUID
    base_confidence: float
    evidence_type: str
    matched_text: str | None


@runtime_checkable
class RelationshipRule(Protocol):
    rule_id: str
    relationship_type: str
    # The unordered entity-type pair(s) this rule applies to, e.g.
    # {frozenset({EntityType.COMPANY, EntityType.PORT})} for "owns".
    applicable_type_pairs: frozenset[frozenset[EntityType]]

    def evaluate(self, candidate: RelationshipCandidate) -> RelationshipFinding | None: ...
