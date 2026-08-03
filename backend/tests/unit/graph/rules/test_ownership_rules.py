"""Unit tests for OWNS (company<->port) and OPERATES (company<->terminal)."""

from app.modules.extraction.models import EntityType
from app.modules.graph.rules.ownership_rules import (
    CompanyOperatesTerminalRule,
    CompanyOwnsPortRule,
)
from tests.unit.graph.rules._factories import make_candidate, make_entity


class TestCompanyOwnsPortRule:
    rule = CompanyOwnsPortRule()

    def test_forward_pattern_company_owns_port(self) -> None:
        company = make_entity(EntityType.COMPANY, "Adani Ports")
        port = make_entity(EntityType.PORT, "Mundra Port")
        candidate = make_candidate(
            "Adani Ports owns Mundra Port.", left_entity=company, right_entity=port
        )

        finding = self.rule.evaluate(candidate)

        assert finding is not None
        assert finding.relationship_type == "owns"
        assert finding.source_entity_id == company.id
        assert finding.target_entity_id == port.id
        assert finding.evidence_type == "text_pattern"

    def test_backward_pattern_port_owned_by_company(self) -> None:
        port = make_entity(EntityType.PORT, "Mundra Port")
        company = make_entity(EntityType.COMPANY, "Adani Ports")
        candidate = make_candidate(
            "Mundra Port owned by Adani Ports.", left_entity=port, right_entity=company
        )

        finding = self.rule.evaluate(candidate)

        assert finding is not None
        # "owned by" means the COMPANY (right side) is the owner - source
        # must resolve to the company, not the textually-first port.
        assert finding.source_entity_id == company.id
        assert finding.target_entity_id == port.id

    def test_no_connecting_pattern_returns_none(self) -> None:
        company = make_entity(EntityType.COMPANY, "Adani Ports")
        port = make_entity(EntityType.PORT, "Mundra Port")
        candidate = make_candidate(
            "Adani Ports acquired Mundra Port.", left_entity=company, right_entity=port
        )

        assert self.rule.evaluate(candidate) is None

    def test_wrong_entity_type_pair_returns_none(self) -> None:
        company = make_entity(EntityType.COMPANY, "Adani Ports")
        commodity = make_entity(EntityType.COMMODITY, "Thermal Coal")
        candidate = make_candidate(
            "Adani Ports owns Thermal Coal.", left_entity=company, right_entity=commodity
        )

        assert self.rule.evaluate(candidate) is None

    def test_reversed_grammar_is_not_flipped(self) -> None:
        """"Port owns Company" is a real but nonsensical claim this
        ontology has no relationship type for - it must be declined, not
        silently reinterpreted as the company owning the port."""
        port = make_entity(EntityType.PORT, "Mundra Port")
        company = make_entity(EntityType.COMPANY, "Adani Ports")
        candidate = make_candidate(
            "Mundra Port owns Adani Ports.", left_entity=port, right_entity=company
        )

        assert self.rule.evaluate(candidate) is None


class TestCompanyOperatesTerminalRule:
    rule = CompanyOperatesTerminalRule()

    def test_forward_pattern(self) -> None:
        company = make_entity(EntityType.COMPANY, "DP World")
        terminal = make_entity(EntityType.TERMINAL, "Terminal 2")
        candidate = make_candidate(
            "DP World operates Terminal 2.", left_entity=company, right_entity=terminal
        )

        finding = self.rule.evaluate(candidate)

        assert finding is not None
        assert finding.relationship_type == "operates"
        assert finding.source_entity_id == company.id
        assert finding.target_entity_id == terminal.id

    def test_backward_pattern(self) -> None:
        terminal = make_entity(EntityType.TERMINAL, "Terminal 2")
        company = make_entity(EntityType.COMPANY, "DP World")
        candidate = make_candidate(
            "Terminal 2 operated by DP World.", left_entity=terminal, right_entity=company
        )

        finding = self.rule.evaluate(candidate)

        assert finding is not None
        assert finding.source_entity_id == company.id
        assert finding.target_entity_id == terminal.id

    def test_no_pattern_match_returns_none(self) -> None:
        company = make_entity(EntityType.COMPANY, "DP World")
        terminal = make_entity(EntityType.TERMINAL, "Terminal 2")
        candidate = make_candidate(
            "DP World built Terminal 2.", left_entity=company, right_entity=terminal
        )

        assert self.rule.evaluate(candidate) is None
