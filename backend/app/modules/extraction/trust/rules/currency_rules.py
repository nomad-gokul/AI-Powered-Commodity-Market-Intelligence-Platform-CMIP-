from app.modules.extraction.models import EntityType, ExtractedEntity
from app.modules.extraction.trust.models import ValidationCategory, ValidationSeverity
from app.modules.extraction.trust.normalization.loader import CanonicalRegistries
from app.modules.extraction.trust.rules.types import ValidationFinding


class InvalidCurrencyRule:
    """Flags a CURRENCY entity whose value doesn't resolve against the
    canonical currency registry (ISO 4217 codes and their common
    symbols/names)."""

    rule_id = "currency.invalid_code"
    validation_type = ValidationCategory.CURRENCY
    applies_to = frozenset({EntityType.CURRENCY})

    def __init__(self, registries: CanonicalRegistries) -> None:
        self._registries = registries

    def evaluate(self, entity: ExtractedEntity) -> ValidationFinding | None:
        raw = entity.normalized_value or entity.raw_value
        match = self._registries.currencies.resolve(raw)
        if match is None:
            return ValidationFinding(
                entity_id=entity.id,
                rule_id=self.rule_id,
                validation_type=self.validation_type,
                severity=ValidationSeverity.ERROR,
                passed=False,
                message=f"{raw!r} is not a recognized currency code",
            )
        return ValidationFinding(
            entity_id=entity.id,
            rule_id=self.rule_id,
            validation_type=self.validation_type,
            severity=ValidationSeverity.INFO,
            passed=True,
            message=f"Resolved to {match.canonical_id}",
        )
