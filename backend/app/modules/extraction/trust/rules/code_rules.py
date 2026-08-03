import re

from app.modules.extraction.models import EntityType, ExtractedEntity
from app.modules.extraction.trust.models import ValidationCategory, ValidationSeverity
from app.modules.extraction.trust.normalization.loader import CanonicalRegistries
from app.modules.extraction.trust.rules.types import ValidationFinding

# HS nomenclature: 2-digit chapter, optionally extended in pairs up to the
# 10-digit national tariff-line level (2/4/6/8/10 digits), with or
# without dot separators between pairs (e.g. "27.10.19" or "27101943").
_HS_CODE_FORMAT_RE = re.compile(r"^\d{2}(\.?\d{2}){0,4}$")


class InvalidHsCodeRule:
    """Flags an HS_CODE entity whose value doesn't even have the right
    shape (digit groups matching the Harmonized System's chapter/heading/
    subheading structure) - a format check, not a full nomenclature
    lookup, since the real HS schedule runs to thousands of lines."""

    rule_id = "hs_code.invalid_format"
    validation_type = ValidationCategory.HS_CODE
    applies_to = frozenset({EntityType.HS_CODE})

    def evaluate(self, entity: ExtractedEntity) -> ValidationFinding | None:
        raw = (entity.normalized_value or entity.raw_value).strip()
        if not _HS_CODE_FORMAT_RE.match(raw):
            return ValidationFinding(
                entity_id=entity.id,
                rule_id=self.rule_id,
                validation_type=self.validation_type,
                severity=ValidationSeverity.ERROR,
                passed=False,
                message=f"{raw!r} is not a valid HS code format",
            )
        return ValidationFinding(
            entity_id=entity.id,
            rule_id=self.rule_id,
            validation_type=self.validation_type,
            severity=ValidationSeverity.INFO,
            passed=True,
            message=f"{raw!r} has a valid HS code format",
        )


class InvalidIncotermRule:
    """Flags an INCOTERM entity that isn't one of the 11 Incoterms® 2020
    trade terms."""

    rule_id = "incoterm.invalid_code"
    validation_type = ValidationCategory.INCOTERM
    applies_to = frozenset({EntityType.INCOTERM})

    def __init__(self, registries: CanonicalRegistries) -> None:
        self._registries = registries

    def evaluate(self, entity: ExtractedEntity) -> ValidationFinding | None:
        raw = entity.normalized_value or entity.raw_value
        match = self._registries.incoterms.resolve(raw)
        if match is None:
            return ValidationFinding(
                entity_id=entity.id,
                rule_id=self.rule_id,
                validation_type=self.validation_type,
                severity=ValidationSeverity.ERROR,
                passed=False,
                message=f"{raw!r} is not a valid Incoterms 2020 code",
            )
        return ValidationFinding(
            entity_id=entity.id,
            rule_id=self.rule_id,
            validation_type=self.validation_type,
            severity=ValidationSeverity.INFO,
            passed=True,
            message=f"Resolved to {match.canonical_id}",
        )
