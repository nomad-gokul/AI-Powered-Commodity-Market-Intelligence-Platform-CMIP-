"""Pure logic for the graph module: which entity types may become graph
nodes, how two co-occurring mentions are ordered and sliced into a
connector string for pattern matching, and how edge confidence is
computed from a rule's base confidence and the two entities' own
trust-pipeline confidence scores. No I/O, no ORM, no LLM - trivially
unit-testable and reused identically by every relationship rule.
"""

from dataclasses import dataclass

from app.modules.extraction.models import EntityMention, EntityType, ExtractedEntity

# The identity-bearing subset of EntityType - the only entity types that
# may become a GraphNode. Excludes currency/price/date/quantity/unit/
# incoterm/hs_code: those describe a node (a price, a quantity, a unit of
# measure), they are never themselves a participant in a business
# relationship graph.
GRAPH_NODE_ELIGIBLE_TYPES: frozenset[EntityType] = frozenset(
    {
        EntityType.COMPANY,
        EntityType.PORT,
        EntityType.COUNTRY,
        EntityType.COMMODITY,
        EntityType.CONTRACT,
        EntityType.TERMINAL,
        EntityType.VESSEL,
        EntityType.ORGANIZATION,
    }
)

# A relationship candidate whose combined confidence falls below this
# floor is discarded entirely, never persisted as a low-confidence edge -
# see combine_edge_confidence.
MIN_EDGE_CONFIDENCE = 0.3

# Two entity mentions are only considered for a text-pattern relationship
# if the connecting text between them is this short or shorter. Bounds
# evidence quality: a "relationship" spanning half a paragraph is not a
# short, direct textual claim and is more likely coincidental
# co-occurrence than a real connection.
MAX_CONNECTOR_CHARS = 80


def clamp(value: float, *, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def combine_edge_confidence(
    base_confidence: float, entity_a_confidence: float, entity_b_confidence: float
) -> float:
    """A relationship built on two low-trust entities should not be
    reported as high confidence: the pattern match's own base confidence
    is scaled by how much we trust the two entities it connects."""
    average_entity_confidence = (entity_a_confidence + entity_b_confidence) / 2
    return clamp(base_confidence * average_entity_confidence)


@dataclass(frozen=True, slots=True)
class OrderedMentionPair:
    """Two entity mentions from the same chunk, ordered left-to-right by
    where they occur in the chunk's text."""

    left_entity: ExtractedEntity
    left_mention: EntityMention
    right_entity: ExtractedEntity
    right_mention: EntityMention


def order_mentions_by_offset(
    entity_a: ExtractedEntity,
    mention_a: EntityMention,
    entity_b: ExtractedEntity,
    mention_b: EntityMention,
) -> OrderedMentionPair | None:
    """Orders two mentions by character_offset. Returns None when either
    mention lacks an offset - without both offsets there is no reliable
    way to slice the connecting text between them, so the pair simply
    cannot be evaluated by any text-pattern rule."""
    if mention_a.character_offset is None or mention_b.character_offset is None:
        return None
    if mention_a.character_offset <= mention_b.character_offset:
        return OrderedMentionPair(entity_a, mention_a, entity_b, mention_b)
    return OrderedMentionPair(entity_b, mention_b, entity_a, mention_a)


def connector_text(
    chunk_text: str, pair: OrderedMentionPair, *, max_gap: int = MAX_CONNECTOR_CHARS
) -> str | None:
    """The text between two ordered mentions, or None if they overlap or
    are farther apart than max_gap. character_offset is nullable-checked
    by order_mentions_by_offset before this is called, so both are
    guaranteed non-None here."""
    left_offset = pair.left_mention.character_offset
    right_offset = pair.right_mention.character_offset
    assert left_offset is not None
    assert right_offset is not None

    left_end = left_offset + len(pair.left_entity.raw_value)
    if left_end > right_offset:
        return None
    gap = chunk_text[left_end:right_offset]
    if len(gap) > max_gap:
        return None
    return gap
