"""Unit tests for every per-entity validation rule."""

from app.modules.extraction.models import EntityType
from app.modules.extraction.trust.models import ValidationSeverity
from app.modules.extraction.trust.normalization.loader import get_canonical_registries
from app.modules.extraction.trust.rules.code_rules import InvalidHsCodeRule, InvalidIncotermRule
from app.modules.extraction.trust.rules.currency_rules import InvalidCurrencyRule
from app.modules.extraction.trust.rules.date_rules import ImpossibleDateRule
from app.modules.extraction.trust.rules.exchange_rate_rules import ImpossibleExchangeRateRule
from app.modules.extraction.trust.rules.geometry_rules import ImpossibleBoundingBoxRule
from app.modules.extraction.trust.rules.quantity_rules import ImpossibleQuantityRule
from app.modules.extraction.trust.rules.unit_rules import UnrecognizedUnitRule
from tests.unit.extraction.trust.rules._factories import make_entity

_REGISTRIES = get_canonical_registries()


class TestImpossibleDateRule:
    rule = ImpossibleDateRule()

    def test_plausible_date_passes(self) -> None:
        entity = make_entity(entity_type=EntityType.DATE, raw_value="2026-01-12")
        finding = self.rule.evaluate(entity)
        assert finding is not None
        assert finding.passed

    def test_unparseable_date_fails(self) -> None:
        entity = make_entity(entity_type=EntityType.DATE, raw_value="not a date")
        finding = self.rule.evaluate(entity)
        assert finding is not None
        assert not finding.passed
        assert finding.severity is ValidationSeverity.ERROR

    def test_implausible_year_fails(self) -> None:
        entity = make_entity(entity_type=EntityType.DATE, raw_value="1400-01-01")
        finding = self.rule.evaluate(entity)
        assert finding is not None
        assert not finding.passed

    def test_prefers_normalized_value_over_raw(self) -> None:
        entity = make_entity(
            entity_type=EntityType.DATE, raw_value="garbage", normalized_value="2026-01-12"
        )
        finding = self.rule.evaluate(entity)
        assert finding is not None
        assert finding.passed


class TestInvalidCurrencyRule:
    rule = InvalidCurrencyRule(_REGISTRIES)

    def test_known_code_passes(self) -> None:
        entity = make_entity(entity_type=EntityType.CURRENCY, raw_value="USD")
        finding = self.rule.evaluate(entity)
        assert finding is not None
        assert finding.passed

    def test_unknown_code_fails(self) -> None:
        entity = make_entity(entity_type=EntityType.CURRENCY, raw_value="ZZZ")
        finding = self.rule.evaluate(entity)
        assert finding is not None
        assert not finding.passed


class TestImpossibleQuantityRule:
    rule = ImpossibleQuantityRule()

    def test_plausible_quantity_passes(self) -> None:
        entity = make_entity(entity_type=EntityType.QUANTITY, raw_value="500 MT")
        finding = self.rule.evaluate(entity)
        assert finding is not None
        assert finding.passed

    def test_negative_quantity_fails(self) -> None:
        entity = make_entity(entity_type=EntityType.QUANTITY, raw_value="-500 MT")
        finding = self.rule.evaluate(entity)
        assert finding is not None
        assert not finding.passed

    def test_absurdly_large_quantity_fails(self) -> None:
        entity = make_entity(entity_type=EntityType.QUANTITY, raw_value="99999999999999 MT")
        finding = self.rule.evaluate(entity)
        assert finding is not None
        assert not finding.passed

    def test_no_numeric_token_fails(self) -> None:
        entity = make_entity(entity_type=EntityType.QUANTITY, raw_value="some tons")
        finding = self.rule.evaluate(entity)
        assert finding is not None
        assert not finding.passed


class TestUnrecognizedUnitRule:
    rule = UnrecognizedUnitRule(_REGISTRIES)

    def test_known_unit_passes(self) -> None:
        entity = make_entity(entity_type=EntityType.UNIT, raw_value="MT")
        finding = self.rule.evaluate(entity)
        assert finding is not None
        assert finding.passed

    def test_unknown_unit_fails_as_warning(self) -> None:
        entity = make_entity(entity_type=EntityType.UNIT, raw_value="furlongs")
        finding = self.rule.evaluate(entity)
        assert finding is not None
        assert not finding.passed
        assert finding.severity is ValidationSeverity.WARNING


class TestInvalidHsCodeRule:
    rule = InvalidHsCodeRule()

    def test_valid_two_digit_chapter_passes(self) -> None:
        entity = make_entity(entity_type=EntityType.HS_CODE, raw_value="27")
        finding = self.rule.evaluate(entity)
        assert finding is not None
        assert finding.passed

    def test_valid_dotted_code_passes(self) -> None:
        entity = make_entity(entity_type=EntityType.HS_CODE, raw_value="27.10.19")
        finding = self.rule.evaluate(entity)
        assert finding is not None
        assert finding.passed

    def test_malformed_code_fails(self) -> None:
        entity = make_entity(entity_type=EntityType.HS_CODE, raw_value="not-a-code")
        finding = self.rule.evaluate(entity)
        assert finding is not None
        assert not finding.passed

    def test_single_digit_fails(self) -> None:
        entity = make_entity(entity_type=EntityType.HS_CODE, raw_value="2")
        finding = self.rule.evaluate(entity)
        assert finding is not None
        assert not finding.passed


class TestInvalidIncotermRule:
    rule = InvalidIncotermRule(_REGISTRIES)

    def test_known_incoterm_passes(self) -> None:
        entity = make_entity(entity_type=EntityType.INCOTERM, raw_value="FOB")
        finding = self.rule.evaluate(entity)
        assert finding is not None
        assert finding.passed

    def test_unknown_incoterm_fails(self) -> None:
        entity = make_entity(entity_type=EntityType.INCOTERM, raw_value="XYZ")
        finding = self.rule.evaluate(entity)
        assert finding is not None
        assert not finding.passed


class TestImpossibleExchangeRateRule:
    rule = ImpossibleExchangeRateRule()

    def test_non_exchange_rate_text_does_not_apply(self) -> None:
        entity = make_entity(entity_type=EntityType.CURRENCY, raw_value="USD")
        assert self.rule.evaluate(entity) is None

    def test_plausible_rate_passes(self) -> None:
        entity = make_entity(entity_type=EntityType.CURRENCY, raw_value="exchange rate: 83.2/USD")
        finding = self.rule.evaluate(entity)
        assert finding is not None
        assert finding.passed

    def test_zero_rate_fails(self) -> None:
        entity = make_entity(entity_type=EntityType.CURRENCY, raw_value="exchange rate: 0/USD")
        finding = self.rule.evaluate(entity)
        assert finding is not None
        assert not finding.passed

    def test_absurd_rate_fails(self) -> None:
        entity = make_entity(
            entity_type=EntityType.PRICE, raw_value="fx rate: 999999999 per USD"
        )
        finding = self.rule.evaluate(entity)
        assert finding is not None
        assert not finding.passed


class TestImpossibleBoundingBoxRule:
    rule = ImpossibleBoundingBoxRule()

    def test_ungrounded_entity_does_not_apply(self) -> None:
        entity = make_entity(entity_type=EntityType.COMMODITY, raw_value="Brent", bounding_box=None)
        assert self.rule.evaluate(entity) is None

    def test_valid_box_passes(self) -> None:
        entity = make_entity(
            entity_type=EntityType.COMMODITY,
            raw_value="Brent",
            bounding_box={"x0": 10.0, "y0": 10.0, "x1": 50.0, "y1": 20.0},
        )
        finding = self.rule.evaluate(entity)
        assert finding is not None
        assert finding.passed

    def test_negative_coordinate_fails(self) -> None:
        entity = make_entity(
            entity_type=EntityType.COMMODITY,
            raw_value="Brent",
            bounding_box={"x0": -5.0, "y0": 10.0, "x1": 50.0, "y1": 20.0},
        )
        finding = self.rule.evaluate(entity)
        assert finding is not None
        assert not finding.passed

    def test_zero_size_box_fails(self) -> None:
        entity = make_entity(
            entity_type=EntityType.COMMODITY,
            raw_value="Brent",
            bounding_box={"x0": 10.0, "y0": 10.0, "x1": 10.0, "y1": 20.0},
        )
        finding = self.rule.evaluate(entity)
        assert finding is not None
        assert not finding.passed

    def test_coordinate_beyond_page_bounds_fails(self) -> None:
        entity = make_entity(
            entity_type=EntityType.COMMODITY,
            raw_value="Brent",
            bounding_box={"x0": 10.0, "y0": 10.0, "x1": 10000.0, "y1": 20.0},
        )
        finding = self.rule.evaluate(entity)
        assert finding is not None
        assert not finding.passed
