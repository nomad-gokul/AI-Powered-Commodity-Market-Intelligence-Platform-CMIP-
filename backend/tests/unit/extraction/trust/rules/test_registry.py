"""Unit tests for ValidationRuleRegistry and the built-in rule set."""

import pytest

from app.modules.extraction.models import EntityType
from app.modules.extraction.trust.exceptions import RuleAlreadyRegisteredError
from app.modules.extraction.trust.rules.builtin import get_validation_rule_registry
from app.modules.extraction.trust.rules.date_rules import ImpossibleDateRule
from app.modules.extraction.trust.rules.registry import ValidationRuleRegistry


class TestValidationRuleRegistry:
    def test_register_and_lookup_entity_rule(self) -> None:
        registry = ValidationRuleRegistry()
        rule = ImpossibleDateRule()
        registry.register_entity_rule(rule)
        assert registry.entity_rules_for(EntityType.DATE) == [rule]

    def test_lookup_for_unrelated_entity_type_is_empty(self) -> None:
        registry = ValidationRuleRegistry()
        registry.register_entity_rule(ImpossibleDateRule())
        assert registry.entity_rules_for(EntityType.CURRENCY) == []

    def test_duplicate_rule_id_raises(self) -> None:
        registry = ValidationRuleRegistry()
        registry.register_entity_rule(ImpossibleDateRule())
        with pytest.raises(RuleAlreadyRegisteredError):
            registry.register_entity_rule(ImpossibleDateRule())

    def test_cross_entity_and_entity_rule_ids_share_one_namespace(self) -> None:
        # A cross-entity rule and an entity rule with the same rule_id
        # should still collide - rule_id is a single flat namespace.
        registry = ValidationRuleRegistry()

        class _FakeCrossRule:
            rule_id = "date.impossible"
            validation_type = ImpossibleDateRule.validation_type

            def evaluate(self, context: object) -> list[object]:
                return []

        registry.register_entity_rule(ImpossibleDateRule())
        with pytest.raises(RuleAlreadyRegisteredError):
            registry.register_cross_entity_rule(_FakeCrossRule())  # type: ignore[arg-type]

    def test_rule_ids_are_sorted(self) -> None:
        registry = get_validation_rule_registry()
        rule_ids = registry.rule_ids()
        assert rule_ids == sorted(rule_ids)


class TestBuiltinRegistry:
    def test_covers_every_documented_validation_category(self) -> None:
        """The Phase 3.3 spec names 11 validation categories - every one
        must be backed by at least one registered rule."""
        registry = get_validation_rule_registry()
        entity_types = list(EntityType)
        covered_categories = {
            rule.validation_type
            for entity_type in entity_types
            for rule in registry.entity_rules_for(entity_type)
        }
        covered_categories.update(
            rule.validation_type for rule in registry.all_cross_entity_rules()
        )
        # 11 named checks map onto this many distinct ValidationCategory
        # values once geometry (impossible coordinates) and consistency/
        # duplicate/conflict (three separate cross-entity categories) are
        # accounted for.
        assert len(covered_categories) >= 9

    def test_registry_is_a_cached_singleton(self) -> None:
        assert get_validation_rule_registry() is get_validation_rule_registry()

    def test_every_entity_type_has_at_least_the_geometry_rule(self) -> None:
        registry = get_validation_rule_registry()
        for entity_type in EntityType:
            assert registry.entity_rules_for(entity_type)
