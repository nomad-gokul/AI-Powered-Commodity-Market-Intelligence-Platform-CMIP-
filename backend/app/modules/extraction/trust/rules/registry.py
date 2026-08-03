"""ValidationRuleRegistry: register/list validation rules by category and
entity type - the "configurable rule registry" the Phase 3.3 spec asks
for, so adding or removing a validation check is a registration call
inside builtin.py, never a new if/elif branch inside ValidationAgent
itself.

Same in-process-registry shape as PromptRegistry
(app/ai/prompts/registry.py) applied to rules instead of prompts - but
without PromptRegistry's immutable versioning: a buggy validation rule
must be fixable in place (re-registering a corrected version under the
same rule_id), unlike a prompt whose exact wording is provenance and must
never change silently.
"""

from app.modules.extraction.models import EntityType
from app.modules.extraction.trust.exceptions import RuleAlreadyRegisteredError
from app.modules.extraction.trust.rules.types import CrossEntityValidationRule, EntityValidationRule


class ValidationRuleRegistry:
    def __init__(self) -> None:
        self._entity_rules: list[EntityValidationRule] = []
        self._cross_entity_rules: list[CrossEntityValidationRule] = []
        self._rule_ids: set[str] = set()

    def register_entity_rule(self, rule: EntityValidationRule) -> None:
        self._claim_id(rule.rule_id)
        self._entity_rules.append(rule)

    def register_cross_entity_rule(self, rule: CrossEntityValidationRule) -> None:
        self._claim_id(rule.rule_id)
        self._cross_entity_rules.append(rule)

    def _claim_id(self, rule_id: str) -> None:
        if rule_id in self._rule_ids:
            raise RuleAlreadyRegisteredError(f"Validation rule {rule_id!r} is already registered")
        self._rule_ids.add(rule_id)

    def entity_rules_for(self, entity_type: EntityType) -> list[EntityValidationRule]:
        return [rule for rule in self._entity_rules if entity_type in rule.applies_to]

    def all_cross_entity_rules(self) -> list[CrossEntityValidationRule]:
        return list(self._cross_entity_rules)

    def rule_ids(self) -> list[str]:
        return sorted(self._rule_ids)
