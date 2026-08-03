"""Registers the 7 built-in relationship rules, one per relationship
named in the Phase 4 spec's examples. RULE_REGISTRY_VERSION is recorded
on graph_build_runs (via GraphBuilderService), mirroring
trust/rules/builtin.py's RULE_REGISTRY_VERSION / prompt_hash's role:
provenance for "which rule set produced this edge."
"""

from functools import lru_cache

from app.modules.graph.rules.location_rules import (
    CompanyLocatedInCountryRule,
    PortLocatedInCountryRule,
)
from app.modules.graph.rules.ownership_rules import (
    CompanyOperatesTerminalRule,
    CompanyOwnsPortRule,
)
from app.modules.graph.rules.reference_rules import ContractReferencesCommodityRule
from app.modules.graph.rules.registry import RelationshipRuleRegistry
from app.modules.graph.rules.shipment_rules import (
    CommodityShippedFromPortRule,
    CommodityShippedToCountryRule,
)

RULE_REGISTRY_VERSION = "1.0"


def register_builtin_rules(registry: RelationshipRuleRegistry) -> None:
    registry.register(CompanyOwnsPortRule())
    registry.register(CompanyOperatesTerminalRule())
    registry.register(CommodityShippedFromPortRule())
    registry.register(CommodityShippedToCountryRule())
    registry.register(ContractReferencesCommodityRule())
    registry.register(CompanyLocatedInCountryRule())
    registry.register(PortLocatedInCountryRule())


@lru_cache(maxsize=1)
def get_relationship_rule_registry() -> RelationshipRuleRegistry:
    registry = RelationshipRuleRegistry()
    register_builtin_rules(registry)
    return registry
