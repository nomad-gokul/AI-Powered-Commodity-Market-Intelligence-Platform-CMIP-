"""Registers every built-in validation rule into a ValidationRuleRegistry.

RULE_REGISTRY_VERSION is recorded on trust_pipeline_runs so a historical
run can always be traced back to exactly which rule set produced it -
bump it whenever a rule's logic changes (not when a bug is merely fixed
in place with identical intent), same spirit as prompt_hash's provenance
guarantee for LLM-facing prompts, just without the immutable-versioning
machinery (see registry.py's docstring for why rules don't need that).
"""

from functools import lru_cache

from app.modules.extraction.trust.normalization.loader import (
    CanonicalRegistries,
    get_canonical_registries,
)
from app.modules.extraction.trust.rules.code_rules import InvalidHsCodeRule, InvalidIncotermRule
from app.modules.extraction.trust.rules.consistency_rules import (
    ConflictingValuesRule,
    DuplicateEntityRule,
    InconsistentTotalsRule,
)
from app.modules.extraction.trust.rules.currency_rules import InvalidCurrencyRule
from app.modules.extraction.trust.rules.date_rules import ImpossibleDateRule
from app.modules.extraction.trust.rules.exchange_rate_rules import ImpossibleExchangeRateRule
from app.modules.extraction.trust.rules.geometry_rules import ImpossibleBoundingBoxRule
from app.modules.extraction.trust.rules.quantity_rules import ImpossibleQuantityRule
from app.modules.extraction.trust.rules.registry import ValidationRuleRegistry
from app.modules.extraction.trust.rules.unit_rules import UnrecognizedUnitRule

RULE_REGISTRY_VERSION = "1.0"


def register_builtin_rules(
    registry: ValidationRuleRegistry, *, registries: CanonicalRegistries
) -> None:
    registry.register_entity_rule(ImpossibleDateRule())
    registry.register_entity_rule(InvalidCurrencyRule(registries))
    registry.register_entity_rule(ImpossibleQuantityRule())
    registry.register_entity_rule(InvalidHsCodeRule())
    registry.register_entity_rule(InvalidIncotermRule(registries))
    registry.register_entity_rule(UnrecognizedUnitRule(registries))
    registry.register_entity_rule(ImpossibleExchangeRateRule())
    registry.register_entity_rule(ImpossibleBoundingBoxRule())

    registry.register_cross_entity_rule(DuplicateEntityRule())
    registry.register_cross_entity_rule(ConflictingValuesRule())
    registry.register_cross_entity_rule(InconsistentTotalsRule())


@lru_cache(maxsize=1)
def get_validation_rule_registry() -> ValidationRuleRegistry:
    registry = ValidationRuleRegistry()
    register_builtin_rules(registry, registries=get_canonical_registries())
    return registry
