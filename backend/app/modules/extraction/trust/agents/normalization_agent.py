"""NormalizationAgent: resolves each entity to a canonical identity or
canonical value. Deterministic, no LLM call.

Closed-set entity types (country, currency, unit, incoterm) resolve
against a static alias table (CanonicalRegistry). Semi-open types
(commodity, port) try the alias table first and fall back to a derived
slug when nothing matches - a real commodity report will mention grades
and ports the seed data doesn't cover. Fully open-set types (company,
organization, vessel, terminal) skip the alias table entirely and go
straight to slug derivation, since no static list could ever enumerate
every real-world company. Value types (date, quantity, price) have no
"identity" to resolve at all - normalization means canonicalizing the
value itself (an ISO date, a value+unit pair, a value+currency pair).
"""

import uuid

from shared.agent_contracts import AgentContext

from app.modules.extraction.models import EntityType, ExtractedEntity
from app.modules.extraction.repository import ExtractedEntityRepository
from app.modules.extraction.trust.agents.schemas import (
    NormalizationAgentOutput,
    NormalizationOutcome,
)
from app.modules.extraction.trust.domain import (
    derive_canonical_id,
    parse_flexible_date,
    parse_numeric,
)
from app.modules.extraction.trust.normalization.canonical_registry import (
    CanonicalMatch,
    CanonicalRegistry,
)
from app.modules.extraction.trust.normalization.loader import CanonicalRegistries

_TYPE_PREFIX = {
    EntityType.COUNTRY: "country",
    EntityType.CURRENCY: "currency",
    EntityType.UNIT: "unit",
    EntityType.INCOTERM: "incoterm",
    EntityType.COMMODITY: "commodity",
    EntityType.PORT: "port",
    EntityType.COMPANY: "company",
    EntityType.ORGANIZATION: "organization",
    EntityType.VESSEL: "vessel",
    EntityType.TERMINAL: "terminal",
    EntityType.CONTRACT: "contract",
}
_CLOSED_SET_TYPES = frozenset(
    {EntityType.COUNTRY, EntityType.CURRENCY, EntityType.UNIT, EntityType.INCOTERM}
)
_ALIAS_WITH_FALLBACK_TYPES = frozenset({EntityType.COMMODITY, EntityType.PORT})
_SLUG_ONLY_TYPES = frozenset(
    {EntityType.COMPANY, EntityType.ORGANIZATION, EntityType.VESSEL, EntityType.TERMINAL}
)

_ALIAS_LOOKUP = "alias_lookup"
_SLUG_DERIVED = "slug_derived"
_SLUG_DERIVED_FALLBACK = "slug_derived_fallback"
_PREFIX_LOOKUP = "prefix_lookup"
_FORMAT_NORMALIZED = "format_normalized"
_LITERAL_NORMALIZED = "literal_normalized"
_VALUE_PARSED = "value_parsed"
_UNRESOLVED = "unresolved"


class NormalizationAgent:
    def __init__(
        self,
        *,
        extraction_run_id: uuid.UUID,
        entity_repo: ExtractedEntityRepository,
        registries: CanonicalRegistries,
    ) -> None:
        self._extraction_run_id = extraction_run_id
        self._entity_repo = entity_repo
        self._registries = registries

    @property
    def name(self) -> str:
        return "normalization"

    async def run(self, context: AgentContext) -> NormalizationAgentOutput:
        entities = await self._entity_repo.list_all_for_run(self._extraction_run_id)
        outcomes = [self._normalize(entity) for entity in entities]
        return NormalizationAgentOutput(outcomes=outcomes)

    def _normalize(self, entity: ExtractedEntity) -> NormalizationOutcome:
        entity_type = entity.entity_type
        raw = entity.normalized_value or entity.raw_value

        if entity_type in _CLOSED_SET_TYPES:
            return self._alias_only(entity, raw, self._registry_for(entity_type))
        if entity_type in _ALIAS_WITH_FALLBACK_TYPES:
            return self._alias_with_slug_fallback(entity, raw)
        if entity_type in _SLUG_ONLY_TYPES:
            return self._slug_only(entity, raw)
        if entity_type == EntityType.HS_CODE:
            return self._hs_code(entity, raw)
        if entity_type == EntityType.CONTRACT:
            return self._contract(entity, raw)
        if entity_type == EntityType.DATE:
            return self._date(entity, raw)
        if entity_type == EntityType.QUANTITY:
            return self._quantity(entity, raw)
        if entity_type == EntityType.PRICE:
            return self._price(entity, raw)
        return self._unresolved(entity)

    def _registry_for(self, entity_type: EntityType) -> CanonicalRegistry:
        return {
            EntityType.COUNTRY: self._registries.countries,
            EntityType.CURRENCY: self._registries.currencies,
            EntityType.UNIT: self._registries.units,
            EntityType.INCOTERM: self._registries.incoterms,
        }[entity_type]

    def _alias_only(
        self, entity: ExtractedEntity, raw: str, registry: CanonicalRegistry
    ) -> NormalizationOutcome:
        match = registry.resolve(raw)
        if match is None:
            return self._unresolved(entity)
        return self._from_match(entity, match, method=_ALIAS_LOOKUP, confidence=1.0)

    def _alias_with_slug_fallback(self, entity: ExtractedEntity, raw: str) -> NormalizationOutcome:
        registry = (
            self._registries.commodities
            if entity.entity_type == EntityType.COMMODITY
            else self._registries.ports
        )
        match = registry.resolve(raw)
        if match is not None:
            return self._from_match(entity, match, method=_ALIAS_LOOKUP, confidence=1.0)
        prefix = _TYPE_PREFIX[entity.entity_type]
        canonical_id = derive_canonical_id(prefix, raw)
        return NormalizationOutcome(
            entity_id=entity.id,
            canonical_id=canonical_id,
            canonical_name=raw.strip(),
            normalized_value=raw.strip(),
            normalization_method=_SLUG_DERIVED_FALLBACK,
            confidence=0.5,
        )

    def _slug_only(self, entity: ExtractedEntity, raw: str) -> NormalizationOutcome:
        prefix = _TYPE_PREFIX[entity.entity_type]
        canonical_id = derive_canonical_id(prefix, raw)
        return NormalizationOutcome(
            entity_id=entity.id,
            canonical_id=canonical_id,
            canonical_name=raw.strip(),
            normalized_value=raw.strip(),
            normalization_method=_SLUG_DERIVED,
            confidence=0.7,
        )

    def _hs_code(self, entity: ExtractedEntity, raw: str) -> NormalizationOutcome:
        match = self._registries.hs_codes.resolve_numeric_prefix(raw, prefix_length=2)
        if match is not None:
            return self._from_match(entity, match, method=_PREFIX_LOOKUP, confidence=0.8)
        digits = "".join(ch for ch in raw if ch.isdigit())
        if len(digits) >= 6:
            return NormalizationOutcome(
                entity_id=entity.id,
                canonical_id=f"hs:{digits[:2]}",
                canonical_name=None,
                normalized_value=digits,
                normalization_method=_FORMAT_NORMALIZED,
                confidence=0.5,
            )
        return self._unresolved(entity)

    def _contract(self, entity: ExtractedEntity, raw: str) -> NormalizationOutcome:
        cleaned = "".join(ch for ch in raw.strip().upper() if ch.isalnum() or ch in "-/")
        if not cleaned:
            return self._unresolved(entity)
        return NormalizationOutcome(
            entity_id=entity.id,
            canonical_id=f"contract:{cleaned}",
            canonical_name=cleaned,
            normalized_value=cleaned,
            normalization_method=_LITERAL_NORMALIZED,
            confidence=0.6,
        )

    def _date(self, entity: ExtractedEntity, raw: str) -> NormalizationOutcome:
        parsed = parse_flexible_date(raw)
        if parsed is None:
            return self._unresolved(entity)
        return NormalizationOutcome(
            entity_id=entity.id,
            canonical_id=None,
            canonical_name=None,
            normalized_value=parsed.isoformat(),
            normalization_method=_VALUE_PARSED,
            confidence=0.9,
        )

    def _quantity(self, entity: ExtractedEntity, raw: str) -> NormalizationOutcome:
        value = parse_numeric(raw)
        if value is None:
            return self._unresolved(entity)
        unit_match = self._find_token_match(self._registries.units, raw)
        if unit_match is not None:
            normalized = f"{value} {unit_match.canonical_id}"
            confidence = 0.9
        else:
            normalized = str(value)
            confidence = 0.6
        return NormalizationOutcome(
            entity_id=entity.id,
            canonical_id=None,
            canonical_name=None,
            normalized_value=normalized,
            normalization_method=_VALUE_PARSED,
            confidence=confidence,
        )

    def _price(self, entity: ExtractedEntity, raw: str) -> NormalizationOutcome:
        value = parse_numeric(raw)
        if value is None:
            return self._unresolved(entity)
        currency_match = self._find_token_match(self._registries.currencies, raw)
        if currency_match is not None:
            normalized = f"{value} {currency_match.canonical_id}"
            confidence = 0.9
        else:
            normalized = str(value)
            confidence = 0.6
        return NormalizationOutcome(
            entity_id=entity.id,
            canonical_id=None,
            canonical_name=None,
            normalized_value=normalized,
            normalization_method=_VALUE_PARSED,
            confidence=confidence,
        )

    @staticmethod
    def _find_token_match(registry: CanonicalRegistry, raw: str) -> CanonicalMatch | None:
        """Tries the whole string first (handles a value that's purely a
        unit/currency symbol), then each whitespace-separated token - lets
        "500 MT" or "$82.14 per barrel" resolve their embedded unit/
        currency token even though the value itself isn't a plain alias."""
        whole = registry.resolve(raw)
        if whole is not None:
            return whole
        for token in raw.replace("$", " $ ").split():
            match = registry.resolve(token.strip("().,"))
            if match is not None:
                return match
        return None

    @staticmethod
    def _from_match(
        entity: ExtractedEntity, match: CanonicalMatch, *, method: str, confidence: float
    ) -> NormalizationOutcome:
        return NormalizationOutcome(
            entity_id=entity.id,
            canonical_id=match.canonical_id,
            canonical_name=match.canonical_name,
            normalized_value=match.canonical_name,
            normalization_method=method,
            confidence=confidence,
        )

    @staticmethod
    def _unresolved(entity: ExtractedEntity) -> NormalizationOutcome:
        return NormalizationOutcome(
            entity_id=entity.id,
            canonical_id=None,
            canonical_name=None,
            normalized_value=None,
            normalization_method=_UNRESOLVED,
            confidence=0.0,
        )
