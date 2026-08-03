"""Unit tests for REFERENCES (contract->commodity), the co-occurrence-
only rule - no connecting verb phrase required, just short proximity."""

from app.modules.extraction.models import EntityType
from app.modules.graph.rules.reference_rules import ContractReferencesCommodityRule
from tests.unit.graph.rules._factories import make_candidate, make_entity


class TestContractReferencesCommodityRule:
    rule = ContractReferencesCommodityRule()

    def test_contract_then_commodity_matches_via_co_occurrence(self) -> None:
        contract = make_entity(EntityType.CONTRACT, "SC-2026-118")
        commodity = make_entity(EntityType.COMMODITY, "thermal coal")
        candidate = make_candidate(
            "Contract SC-2026-118 covers 50,000 MT of thermal coal.",
            left_entity=contract,
            right_entity=commodity,
        )

        finding = self.rule.evaluate(candidate)

        assert finding is not None
        assert finding.relationship_type == "references"
        assert finding.source_entity_id == contract.id
        assert finding.target_entity_id == commodity.id
        assert finding.evidence_type == "co_occurrence"
        assert finding.matched_text is None

    def test_commodity_then_contract_still_resolves_contract_as_source(self) -> None:
        commodity = make_entity(EntityType.COMMODITY, "thermal coal")
        contract = make_entity(EntityType.CONTRACT, "SC-2026-118")
        candidate = make_candidate(
            "The thermal coal volumes are set out in SC-2026-118.",
            left_entity=commodity,
            right_entity=contract,
        )

        finding = self.rule.evaluate(candidate)

        assert finding is not None
        assert finding.source_entity_id == contract.id
        assert finding.target_entity_id == commodity.id

    def test_too_far_apart_returns_none(self) -> None:
        contract = make_entity(EntityType.CONTRACT, "SC-2026-118")
        commodity = make_entity(EntityType.COMMODITY, "thermal coal")
        filler = "x" * 200
        candidate = make_candidate(
            f"Contract SC-2026-118 {filler} thermal coal",
            left_entity=contract,
            right_entity=commodity,
        )

        assert self.rule.evaluate(candidate) is None

    def test_wrong_type_pair_returns_none(self) -> None:
        company = make_entity(EntityType.COMPANY, "Adani Ports")
        commodity = make_entity(EntityType.COMMODITY, "thermal coal")
        candidate = make_candidate(
            "Adani Ports handles thermal coal.", left_entity=company, right_entity=commodity
        )

        assert self.rule.evaluate(candidate) is None
