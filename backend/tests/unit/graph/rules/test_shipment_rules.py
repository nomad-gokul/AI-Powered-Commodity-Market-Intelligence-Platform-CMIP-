"""Unit tests for SHIPPED_FROM (commodity->port) and SHIPPED_TO
(commodity->country)."""

from app.modules.extraction.models import EntityType
from app.modules.graph.rules.shipment_rules import (
    CommodityShippedFromPortRule,
    CommodityShippedToCountryRule,
)
from tests.unit.graph.rules._factories import make_candidate, make_entity


class TestCommodityShippedFromPortRule:
    rule = CommodityShippedFromPortRule()

    def test_forward_pattern_matches(self) -> None:
        commodity = make_entity(EntityType.COMMODITY, "Brent crude")
        port = make_entity(EntityType.PORT, "Rotterdam")
        candidate = make_candidate(
            "Brent crude shipped from Rotterdam.", left_entity=commodity, right_entity=port
        )

        finding = self.rule.evaluate(candidate)

        assert finding is not None
        assert finding.relationship_type == "shipped_from"
        assert finding.source_entity_id == commodity.id
        assert finding.target_entity_id == port.id

    def test_alternate_keyword_loaded_at(self) -> None:
        commodity = make_entity(EntityType.COMMODITY, "Brent crude")
        port = make_entity(EntityType.PORT, "Rotterdam")
        candidate = make_candidate(
            "Brent crude loaded at Rotterdam.", left_entity=commodity, right_entity=port
        )

        assert self.rule.evaluate(candidate) is not None

    def test_reversed_order_does_not_match(self) -> None:
        port = make_entity(EntityType.PORT, "Rotterdam")
        commodity = make_entity(EntityType.COMMODITY, "Brent crude")
        candidate = make_candidate(
            "Rotterdam received Brent crude shipped from there.",
            left_entity=port,
            right_entity=commodity,
        )

        assert self.rule.evaluate(candidate) is None

    def test_no_pattern_returns_none(self) -> None:
        commodity = make_entity(EntityType.COMMODITY, "Brent crude")
        port = make_entity(EntityType.PORT, "Rotterdam")
        candidate = make_candidate(
            "Brent crude priced at Rotterdam.", left_entity=commodity, right_entity=port
        )

        assert self.rule.evaluate(candidate) is None


class TestCommodityShippedToCountryRule:
    rule = CommodityShippedToCountryRule()

    def test_forward_pattern_matches(self) -> None:
        commodity = make_entity(EntityType.COMMODITY, "Thermal coal")
        country = make_entity(EntityType.COUNTRY, "India")
        candidate = make_candidate(
            "Thermal coal shipped to India.", left_entity=commodity, right_entity=country
        )

        finding = self.rule.evaluate(candidate)

        assert finding is not None
        assert finding.relationship_type == "shipped_to"
        assert finding.source_entity_id == commodity.id
        assert finding.target_entity_id == country.id

    def test_alternate_keyword_bound_for(self) -> None:
        commodity = make_entity(EntityType.COMMODITY, "Thermal coal")
        country = make_entity(EntityType.COUNTRY, "India")
        candidate = make_candidate(
            "Thermal coal bound for India.", left_entity=commodity, right_entity=country
        )

        assert self.rule.evaluate(candidate) is not None

    def test_wrong_type_pair_returns_none(self) -> None:
        commodity = make_entity(EntityType.COMMODITY, "Thermal coal")
        port = make_entity(EntityType.PORT, "Mundra")
        candidate = make_candidate(
            "Thermal coal shipped to Mundra.", left_entity=commodity, right_entity=port
        )

        assert self.rule.evaluate(candidate) is None
