"""Unit tests for LOCATED_IN (company->country, port->country)."""

from app.modules.extraction.models import EntityType
from app.modules.graph.rules.location_rules import (
    CompanyLocatedInCountryRule,
    PortLocatedInCountryRule,
)
from tests.unit.graph.rules._factories import make_candidate, make_entity


class TestCompanyLocatedInCountryRule:
    rule = CompanyLocatedInCountryRule()

    def test_headquartered_in_matches(self) -> None:
        company = make_entity(EntityType.COMPANY, "Adani Ports")
        country = make_entity(EntityType.COUNTRY, "India")
        candidate = make_candidate(
            "Adani Ports headquartered in India.", left_entity=company, right_entity=country
        )

        finding = self.rule.evaluate(candidate)

        assert finding is not None
        assert finding.relationship_type == "located_in"
        assert finding.source_entity_id == company.id
        assert finding.target_entity_id == country.id
        assert finding.evidence_type == "text_pattern"

    def test_no_pattern_returns_none(self) -> None:
        company = make_entity(EntityType.COMPANY, "Adani Ports")
        country = make_entity(EntityType.COUNTRY, "India")
        candidate = make_candidate(
            "Adani Ports trades with India.", left_entity=company, right_entity=country
        )

        assert self.rule.evaluate(candidate) is None


class TestPortLocatedInCountryRule:
    rule = PortLocatedInCountryRule()

    def test_verb_pattern_matches_with_higher_confidence(self) -> None:
        port = make_entity(EntityType.PORT, "Mundra Port")
        country = make_entity(EntityType.COUNTRY, "India")
        candidate = make_candidate(
            "Mundra Port located in India.", left_entity=port, right_entity=country
        )

        finding = self.rule.evaluate(candidate)

        assert finding is not None
        assert finding.evidence_type == "text_pattern"
        assert finding.base_confidence == self.rule.verb_base_confidence

    def test_comma_adjacency_matches_with_lower_confidence(self) -> None:
        port = make_entity(EntityType.PORT, "Mundra")
        country = make_entity(EntityType.COUNTRY, "India")
        candidate = make_candidate("Mundra, India.", left_entity=port, right_entity=country)

        finding = self.rule.evaluate(candidate)

        assert finding is not None
        assert finding.evidence_type == "adjacent_mention"
        assert finding.base_confidence == self.rule.adjacency_base_confidence
        assert finding.base_confidence < self.rule.verb_base_confidence

    def test_unrelated_text_between_mentions_returns_none(self) -> None:
        port = make_entity(EntityType.PORT, "Mundra")
        country = make_entity(EntityType.COUNTRY, "India")
        candidate = make_candidate(
            "Mundra is a major port serving India.", left_entity=port, right_entity=country
        )

        assert self.rule.evaluate(candidate) is None

    def test_wrong_type_pair_returns_none(self) -> None:
        company = make_entity(EntityType.COMPANY, "Adani Ports")
        country = make_entity(EntityType.COUNTRY, "India")
        candidate = make_candidate(
            "Adani Ports, India.", left_entity=company, right_entity=country
        )

        assert self.rule.evaluate(candidate) is None
