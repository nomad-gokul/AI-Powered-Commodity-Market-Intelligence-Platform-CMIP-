"""Unit tests for graph/domain.py's pure logic: node-type eligibility,
mention ordering, connector-text slicing, and confidence combination."""

import uuid

from app.modules.extraction.models import EntityMention, EntityType, ExtractedEntity
from app.modules.graph.domain import (
    GRAPH_NODE_ELIGIBLE_TYPES,
    MIN_EDGE_CONFIDENCE,
    clamp,
    combine_edge_confidence,
    connector_text,
    order_mentions_by_offset,
)


def _entity(entity_type: EntityType, raw_value: str) -> ExtractedEntity:
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


def _mention(entity_id: uuid.UUID, *, character_offset: int | None) -> EntityMention:
    return EntityMention(
        id=uuid.uuid4(),
        entity_id=entity_id,
        page_number=1,
        character_offset=character_offset,
        surrounding_text="...",
        source_chunk=uuid.uuid4(),
    )


class TestGraphNodeEligibleTypes:
    def test_identity_bearing_types_are_eligible(self) -> None:
        for entity_type in (
            EntityType.COMPANY,
            EntityType.PORT,
            EntityType.COUNTRY,
            EntityType.COMMODITY,
            EntityType.CONTRACT,
            EntityType.TERMINAL,
            EntityType.VESSEL,
            EntityType.ORGANIZATION,
        ):
            assert entity_type in GRAPH_NODE_ELIGIBLE_TYPES

    def test_attribute_types_are_not_eligible(self) -> None:
        for entity_type in (
            EntityType.CURRENCY,
            EntityType.PRICE,
            EntityType.DATE,
            EntityType.QUANTITY,
            EntityType.UNIT,
            EntityType.INCOTERM,
            EntityType.HS_CODE,
        ):
            assert entity_type not in GRAPH_NODE_ELIGIBLE_TYPES


class TestClamp:
    def test_clamps_below_floor(self) -> None:
        assert clamp(-0.5) == 0.0

    def test_clamps_above_ceiling(self) -> None:
        assert clamp(1.5) == 1.0

    def test_passes_through_in_range_value(self) -> None:
        assert clamp(0.42) == 0.42


class TestCombineEdgeConfidence:
    def test_multiplies_base_by_average_entity_confidence(self) -> None:
        assert combine_edge_confidence(0.8, 1.0, 1.0) == 0.8
        assert combine_edge_confidence(0.8, 0.5, 0.5) == 0.4

    def test_result_is_clamped(self) -> None:
        assert combine_edge_confidence(1.5, 1.0, 1.0) == 1.0

    def test_low_entity_confidence_can_fall_below_min_edge_confidence(self) -> None:
        result = combine_edge_confidence(0.55, 0.2, 0.2)
        assert result < MIN_EDGE_CONFIDENCE


class TestOrderMentionsByOffset:
    def test_orders_left_to_right_by_offset(self) -> None:
        entity_a = _entity(EntityType.COMPANY, "Adani Ports")
        entity_b = _entity(EntityType.PORT, "Mundra")
        mention_a = _mention(entity_a.id, character_offset=20)
        mention_b = _mention(entity_b.id, character_offset=5)

        ordered = order_mentions_by_offset(entity_a, mention_a, entity_b, mention_b)

        assert ordered is not None
        assert ordered.left_entity is entity_b
        assert ordered.right_entity is entity_a

    def test_already_ordered_pair_stays_in_place(self) -> None:
        entity_a = _entity(EntityType.COMPANY, "Adani Ports")
        entity_b = _entity(EntityType.PORT, "Mundra")
        mention_a = _mention(entity_a.id, character_offset=5)
        mention_b = _mention(entity_b.id, character_offset=20)

        ordered = order_mentions_by_offset(entity_a, mention_a, entity_b, mention_b)

        assert ordered is not None
        assert ordered.left_entity is entity_a
        assert ordered.right_entity is entity_b

    def test_missing_offset_on_either_side_returns_none(self) -> None:
        entity_a = _entity(EntityType.COMPANY, "Adani Ports")
        entity_b = _entity(EntityType.PORT, "Mundra")
        mention_a = _mention(entity_a.id, character_offset=None)
        mention_b = _mention(entity_b.id, character_offset=20)

        assert order_mentions_by_offset(entity_a, mention_a, entity_b, mention_b) is None
        assert order_mentions_by_offset(entity_b, mention_b, entity_a, mention_a) is None


class TestConnectorText:
    def test_returns_text_between_two_mentions(self) -> None:
        chunk_text = "Adani Ports owns Mundra Port in Gujarat."
        entity_a = _entity(EntityType.COMPANY, "Adani Ports")
        entity_b = _entity(EntityType.PORT, "Mundra Port")
        mention_a = _mention(entity_a.id, character_offset=0)
        mention_b = _mention(entity_b.id, character_offset=chunk_text.index("Mundra Port"))

        ordered = order_mentions_by_offset(entity_a, mention_a, entity_b, mention_b)
        assert ordered is not None
        connector = connector_text(chunk_text, ordered)

        assert connector == " owns "

    def test_overlapping_mentions_return_none(self) -> None:
        chunk_text = "Adani Ports Mundra overlap case"
        entity_a = _entity(EntityType.COMPANY, "Adani Ports Mundra")
        entity_b = _entity(EntityType.PORT, "Mundra")
        mention_a = _mention(entity_a.id, character_offset=0)
        mention_b = _mention(entity_b.id, character_offset=5)

        ordered = order_mentions_by_offset(entity_a, mention_a, entity_b, mention_b)
        assert ordered is not None
        assert connector_text(chunk_text, ordered) is None

    def test_mentions_farther_apart_than_max_gap_return_none(self) -> None:
        chunk_text = "Adani Ports " + ("x" * 200) + " Mundra Port"
        entity_a = _entity(EntityType.COMPANY, "Adani Ports")
        entity_b = _entity(EntityType.PORT, "Mundra Port")
        mention_a = _mention(entity_a.id, character_offset=0)
        mention_b = _mention(entity_b.id, character_offset=len(chunk_text) - len("Mundra Port"))

        ordered = order_mentions_by_offset(entity_a, mention_a, entity_b, mention_b)
        assert ordered is not None
        assert connector_text(chunk_text, ordered, max_gap=80) is None
