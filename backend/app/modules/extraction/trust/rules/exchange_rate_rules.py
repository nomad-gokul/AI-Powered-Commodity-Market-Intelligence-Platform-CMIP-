import re

from app.modules.extraction.models import EntityType, ExtractedEntity
from app.modules.extraction.trust.domain import parse_numeric
from app.modules.extraction.trust.models import ValidationCategory, ValidationSeverity
from app.modules.extraction.trust.rules.types import ValidationFinding

# Phase 3.2's EntityType enum has no dedicated EXCHANGE_RATE type (adding
# one would mean asking EntityExtractionAgent to extract a new kind of
# entity, which is explicitly out of scope this phase - "the objective is
# not to extract more data"). Exchange rates instead show up embedded in
# CURRENCY/PRICE entities' raw text ("1 USD = 83.2 INR", "83.2/USD",
# "exchange rate: 83.2") - this rule only fires when that shape is
# present, so it never mistakes an ordinary price for an exchange rate.
_EXCHANGE_RATE_HINT_RE = re.compile(
    r"exchange rate|fx rate|/\s?[a-z]{3}\b|per\s+[a-z]{3}\b", re.IGNORECASE
)
_MIN_PLAUSIBLE_RATE = 1e-4
_MAX_PLAUSIBLE_RATE = 1e4


class ImpossibleExchangeRateRule:
    """Flags an exchange-rate-shaped value that is zero, negative, or so
    far outside any real currency pair's historical range that it's
    almost certainly an extraction error."""

    rule_id = "exchange_rate.impossible"
    validation_type = ValidationCategory.EXCHANGE_RATE
    applies_to = frozenset({EntityType.CURRENCY, EntityType.PRICE})

    def evaluate(self, entity: ExtractedEntity) -> ValidationFinding | None:
        if not _EXCHANGE_RATE_HINT_RE.search(entity.raw_value):
            return None

        value = parse_numeric(entity.normalized_value or entity.raw_value)
        if value is None:
            return None

        if value <= 0 or value < _MIN_PLAUSIBLE_RATE or value > _MAX_PLAUSIBLE_RATE:
            return ValidationFinding(
                entity_id=entity.id,
                rule_id=self.rule_id,
                validation_type=self.validation_type,
                severity=ValidationSeverity.ERROR,
                passed=False,
                message=f"Exchange rate {value} is outside a plausible range",
            )
        return ValidationFinding(
            entity_id=entity.id,
            rule_id=self.rule_id,
            validation_type=self.validation_type,
            severity=ValidationSeverity.INFO,
            passed=True,
            message=f"Exchange rate {value} is plausible",
        )
