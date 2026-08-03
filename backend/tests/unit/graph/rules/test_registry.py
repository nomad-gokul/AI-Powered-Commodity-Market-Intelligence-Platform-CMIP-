"""Unit tests for RelationshipRuleRegistry and the built-in rule set."""

import pytest

from app.modules.extraction.models import EntityType
from app.modules.graph.exceptions import RuleAlreadyRegisteredError
from app.modules.graph.rules.builtin import get_relationship_rule_registry
from app.modules.graph.rules.ownership_rules import CompanyOwnsPortRule
from app.modules.graph.rules.registry import RelationshipRuleRegistry


class TestRelationshipRuleRegistry:
    def test_register_and_lookup_by_type_pair(self) -> None:
        registry = RelationshipRuleRegistry()
        rule = CompanyOwnsPortRule()
        registry.register(rule)
        assert registry.rules_for_type_pair(EntityType.COMPANY, EntityType.PORT) == [rule]

    def test_lookup_is_order_independent(self) -> None:
        registry = RelationshipRuleRegistry()
        rule = CompanyOwnsPortRule()
        registry.register(rule)
        assert registry.rules_for_type_pair(EntityType.PORT, EntityType.COMPANY) == [rule]

    def test_lookup_for_unrelated_type_pair_is_empty(self) -> None:
        registry = RelationshipRuleRegistry()
        registry.register(CompanyOwnsPortRule())
        assert registry.rules_for_type_pair(EntityType.COMMODITY, EntityType.COUNTRY) == []

    def test_duplicate_rule_id_raises(self) -> None:
        registry = RelationshipRuleRegistry()
        registry.register(CompanyOwnsPortRule())
        with pytest.raises(RuleAlreadyRegisteredError):
            registry.register(CompanyOwnsPortRule())

    def test_len_reflects_registered_rule_count(self) -> None:
        registry = RelationshipRuleRegistry()
        assert len(registry) == 0
        registry.register(CompanyOwnsPortRule())
        assert len(registry) == 1

    def test_rule_ids_are_sorted(self) -> None:
        registry = get_relationship_rule_registry()
        rule_ids = registry.rule_ids()
        assert rule_ids == sorted(rule_ids)


class TestBuiltinRegistry:
    def test_covers_every_documented_example_relationship(self) -> None:
        """The Phase 4 spec names 7 example relationships - every one
        must be backed by a registered rule reachable via its entity
        type pair."""
        registry = get_relationship_rule_registry()
        expected_pairs = [
            (EntityType.COMPANY, EntityType.PORT),
            (EntityType.COMPANY, EntityType.TERMINAL),
            (EntityType.COMMODITY, EntityType.PORT),
            (EntityType.COMMODITY, EntityType.COUNTRY),
            (EntityType.CONTRACT, EntityType.COMMODITY),
            (EntityType.COMPANY, EntityType.COUNTRY),
            (EntityType.PORT, EntityType.COUNTRY),
        ]
        for type_a, type_b in expected_pairs:
            assert registry.rules_for_type_pair(type_a, type_b), (type_a, type_b)

    def test_registry_is_a_cached_singleton(self) -> None:
        assert get_relationship_rule_registry() is get_relationship_rule_registry()

    def test_exactly_seven_builtin_rules(self) -> None:
        assert len(get_relationship_rule_registry()) == 7
