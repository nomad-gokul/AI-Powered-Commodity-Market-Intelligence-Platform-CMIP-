from app.modules.extraction.models import EntityType, ExtractedEntity
from app.modules.extraction.trust.models import ValidationCategory, ValidationSeverity
from app.modules.extraction.trust.normalization.loader import CanonicalRegistries
from app.modules.extraction.trust.rules.types import ValidationFinding


class UnrecognizedUnitRule:
    """Flags a UNIT entity that doesn't resolve against the canonical unit
    registry - the closest tractable reading of "inconsistent units" that
    doesn't require inventing a full dimensional-analysis engine: a unit
    we can't place in a known dimension (mass/volume/energy/count) can't
    be checked for consistency against anything else either, so it goes
    to review instead of being silently accepted."""

    rule_id = "unit.unrecognized"
    validation_type = ValidationCategory.UNIT
    applies_to = frozenset({EntityType.UNIT})

    def __init__(self, registries: CanonicalRegistries) -> None:
        self._registries = registries

    def evaluate(self, entity: ExtractedEntity) -> ValidationFinding | None:
        raw = entity.normalized_value or entity.raw_value
        match = self._registries.units.resolve(raw)
        if match is None:
            return ValidationFinding(
                entity_id=entity.id,
                rule_id=self.rule_id,
                validation_type=self.validation_type,
                severity=ValidationSeverity.WARNING,
                passed=False,
                message=f"{raw!r} is not a recognized unit",
            )
        return ValidationFinding(
            entity_id=entity.id,
            rule_id=self.rule_id,
            validation_type=self.validation_type,
            severity=ValidationSeverity.INFO,
            passed=True,
            message=f"Resolved to {match.canonical_id}",
        )
