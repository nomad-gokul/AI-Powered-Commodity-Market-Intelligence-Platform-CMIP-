"""In-process registry of relationship rules, keyed by the unordered
entity-type pair they apply to. Deliberately NOT immutable/versioned
like PromptRegistry - a buggy relationship rule must be fixable in
place, same reasoning as trust/rules/registry.py's ValidationRuleRegistry.
"""

from collections import defaultdict

from app.modules.extraction.models import EntityType
from app.modules.graph.exceptions import RuleAlreadyRegisteredError
from app.modules.graph.rules.types import RelationshipRule


class RelationshipRuleRegistry:
    def __init__(self) -> None:
        self._rules_by_id: dict[str, RelationshipRule] = {}
        self._rules_by_pair: dict[frozenset[EntityType], list[RelationshipRule]] = defaultdict(list)

    def register(self, rule: RelationshipRule) -> None:
        if rule.rule_id in self._rules_by_id:
            raise RuleAlreadyRegisteredError(
                f"Relationship rule '{rule.rule_id}' is already registered"
            )
        self._rules_by_id[rule.rule_id] = rule
        for pair in rule.applicable_type_pairs:
            self._rules_by_pair[pair].append(rule)

    def rules_for_type_pair(
        self, entity_type_a: EntityType, entity_type_b: EntityType
    ) -> list[RelationshipRule]:
        return list(self._rules_by_pair.get(frozenset({entity_type_a, entity_type_b}), []))

    def rule_ids(self) -> list[str]:
        return sorted(self._rules_by_id.keys())

    def __len__(self) -> int:
        return len(self._rules_by_id)
