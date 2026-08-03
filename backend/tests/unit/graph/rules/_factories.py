"""Shared in-memory entity/mention/candidate factories for relationship
rule unit tests - plain ORM object construction (never persisted)."""

import uuid

from app.modules.extraction.models import EntityMention, EntityType, ExtractedEntity
from app.modules.graph.domain import order_mentions_by_offset
from app.modules.graph.rules.types import RelationshipCandidate


def make_entity(entity_type: EntityType, raw_value: str) -> ExtractedEntity:
    return ExtractedEntity(
        id=uuid.uuid4(),
        extraction_run_id=uuid.uuid4(),
        entity_type=entity_type,
        raw_value=raw_value,
        normalized_value=None,
        confidence=0.9,
        page_number=1,
        bounding_box=None,
        provider="groq",
        model="test-model",
        prompt_version="1.0",
    )


def make_mention(entity_id: uuid.UUID, *, character_offset: int) -> EntityMention:
    return EntityMention(
        id=uuid.uuid4(),
        entity_id=entity_id,
        page_number=1,
        character_offset=character_offset,
        surrounding_text="...",
        source_chunk=uuid.uuid4(),
    )


def make_candidate(
    chunk_text: str,
    *,
    left_entity: ExtractedEntity,
    right_entity: ExtractedEntity,
) -> RelationshipCandidate:
    """Builds a RelationshipCandidate from two entities already known to
    appear in that left-to-right order in chunk_text - offsets are found
    via str.index rather than hand-counted, so a typo in the fixture
    text raises ValueError instead of silently misaligning the test."""
    left_offset = chunk_text.index(left_entity.raw_value)
    right_offset = chunk_text.index(
        right_entity.raw_value, left_offset + len(left_entity.raw_value)
    )
    left_mention = make_mention(left_entity.id, character_offset=left_offset)
    right_mention = make_mention(right_entity.id, character_offset=right_offset)
    ordered = order_mentions_by_offset(left_entity, left_mention, right_entity, right_mention)
    assert ordered is not None
    return RelationshipCandidate(pair=ordered, chunk_text=chunk_text)
