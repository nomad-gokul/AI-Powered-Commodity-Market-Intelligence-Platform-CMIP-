from app.modules.extraction.models import EntityType, ExtractedEntity
from app.modules.extraction.trust.domain import parse_numeric
from app.modules.extraction.trust.models import ValidationCategory, ValidationSeverity
from app.modules.extraction.trust.rules.types import ValidationFinding

_MAX_PLAUSIBLE_QUANTITY = 1e12


class ImpossibleQuantityRule:
    """Flags a QUANTITY entity with no numeric value at all, a negative
    value, or a value so large it's more likely an OCR/extraction error
    than a real traded quantity (larger than global annual production of
    any single commodity)."""

    rule_id = "quantity.impossible"
    validation_type = ValidationCategory.QUANTITY
    applies_to = frozenset({EntityType.QUANTITY})

    def evaluate(self, entity: ExtractedEntity) -> ValidationFinding | None:
        raw = entity.normalized_value or entity.raw_value
        value = parse_numeric(raw)
        if value is None:
            return ValidationFinding(
                entity_id=entity.id,
                rule_id=self.rule_id,
                validation_type=self.validation_type,
                severity=ValidationSeverity.ERROR,
                passed=False,
                message=f"No numeric quantity found in {raw!r}",
            )
        if value < 0 or value > _MAX_PLAUSIBLE_QUANTITY:
            return ValidationFinding(
                entity_id=entity.id,
                rule_id=self.rule_id,
                validation_type=self.validation_type,
                severity=ValidationSeverity.ERROR,
                passed=False,
                message=f"Quantity {value} is outside a plausible range",
            )
        return ValidationFinding(
            entity_id=entity.id,
            rule_id=self.rule_id,
            validation_type=self.validation_type,
            severity=ValidationSeverity.INFO,
            passed=True,
            message=f"Quantity {value} is plausible",
        )
