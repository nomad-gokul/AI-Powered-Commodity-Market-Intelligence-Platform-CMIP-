from datetime import date

from app.modules.extraction.models import EntityType, ExtractedEntity
from app.modules.extraction.trust.domain import parse_flexible_date
from app.modules.extraction.trust.models import ValidationCategory, ValidationSeverity
from app.modules.extraction.trust.rules.types import ValidationFinding

_MIN_PLAUSIBLE_YEAR = 1990
_MAX_YEARS_AHEAD = 5


class ImpossibleDateRule:
    """Flags a DATE entity whose value doesn't parse as a real calendar
    date, or whose year is outside a plausible window for a commodity
    market report (too far in the past to be a live report, or further in
    the future than any real contract/delivery date would reasonably be)."""

    rule_id = "date.impossible"
    validation_type = ValidationCategory.DATE
    applies_to = frozenset({EntityType.DATE})

    def evaluate(self, entity: ExtractedEntity) -> ValidationFinding | None:
        raw = entity.normalized_value or entity.raw_value
        parsed = parse_flexible_date(raw)
        if parsed is None:
            return ValidationFinding(
                entity_id=entity.id,
                rule_id=self.rule_id,
                validation_type=self.validation_type,
                severity=ValidationSeverity.ERROR,
                passed=False,
                message=f"Could not parse {raw!r} as a calendar date",
            )

        max_year = date.today().year + _MAX_YEARS_AHEAD
        if parsed.year < _MIN_PLAUSIBLE_YEAR or parsed.year > max_year:
            return ValidationFinding(
                entity_id=entity.id,
                rule_id=self.rule_id,
                validation_type=self.validation_type,
                severity=ValidationSeverity.ERROR,
                passed=False,
                message=f"Date {parsed.isoformat()} has an implausible year for a market report",
            )
        return ValidationFinding(
            entity_id=entity.id,
            rule_id=self.rule_id,
            validation_type=self.validation_type,
            severity=ValidationSeverity.INFO,
            passed=True,
            message=f"Date {parsed.isoformat()} is plausible",
        )
