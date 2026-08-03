"""Unit tests for the cross-entity validation rules: duplicates,
conflicting values, and table-total reconciliation."""

from app.modules.extraction.models import EntityType
from app.modules.extraction.trust.rules.consistency_rules import (
    ConflictingValuesRule,
    DuplicateEntityRule,
    InconsistentTotalsRule,
)
from app.modules.extraction.trust.rules.types import ValidationContext
from tests.unit.extraction.trust.rules._factories import make_cell, make_entity, make_table


class TestDuplicateEntityRule:
    rule = DuplicateEntityRule()

    def test_no_duplicates_produces_no_findings(self) -> None:
        entities = [
            make_entity(entity_type=EntityType.COMMODITY, raw_value="Brent", page_number=1),
            make_entity(entity_type=EntityType.COMMODITY, raw_value="WTI", page_number=1),
        ]
        context = ValidationContext(entities=entities, tables=[], cells_by_table={})
        assert self.rule.evaluate(context) == []

    def test_same_type_text_and_page_flags_the_second(self) -> None:
        first = make_entity(entity_type=EntityType.COMMODITY, raw_value="Brent", page_number=1)
        second = make_entity(entity_type=EntityType.COMMODITY, raw_value="Brent", page_number=1)
        context = ValidationContext(entities=[first, second], tables=[], cells_by_table={})
        findings = self.rule.evaluate(context)
        assert len(findings) == 1
        assert findings[0].entity_id == second.id
        assert not findings[0].passed

    def test_case_and_whitespace_insensitive_match(self) -> None:
        first = make_entity(entity_type=EntityType.COMMODITY, raw_value="Brent", page_number=1)
        second = make_entity(entity_type=EntityType.COMMODITY, raw_value="  brent  ", page_number=1)
        context = ValidationContext(entities=[first, second], tables=[], cells_by_table={})
        assert len(self.rule.evaluate(context)) == 1

    def test_different_pages_are_not_duplicates(self) -> None:
        first = make_entity(entity_type=EntityType.COMMODITY, raw_value="Brent", page_number=1)
        second = make_entity(entity_type=EntityType.COMMODITY, raw_value="Brent", page_number=2)
        context = ValidationContext(entities=[first, second], tables=[], cells_by_table={})
        assert self.rule.evaluate(context) == []

    def test_different_entity_types_are_not_duplicates(self) -> None:
        first = make_entity(entity_type=EntityType.COMMODITY, raw_value="Brent", page_number=1)
        second = make_entity(entity_type=EntityType.PORT, raw_value="Brent", page_number=1)
        context = ValidationContext(entities=[first, second], tables=[], cells_by_table={})
        assert self.rule.evaluate(context) == []


class TestConflictingValuesRule:
    rule = ConflictingValuesRule()

    def test_same_text_agreeing_values_produces_no_findings(self) -> None:
        first = make_entity(
            entity_type=EntityType.PRICE, raw_value="82.14", normalized_value="82.14", page_number=1
        )
        second = make_entity(
            entity_type=EntityType.PRICE, raw_value="82.14", normalized_value="82.14", page_number=1
        )
        context = ValidationContext(entities=[first, second], tables=[], cells_by_table={})
        assert self.rule.evaluate(context) == []

    def test_same_text_disagreeing_values_flags_the_second(self) -> None:
        first = make_entity(
            entity_type=EntityType.PRICE,
            raw_value="Dated Brent",
            normalized_value="82.14",
            page_number=1,
        )
        second = make_entity(
            entity_type=EntityType.PRICE,
            raw_value="Dated Brent",
            normalized_value="95.00",
            page_number=1,
        )
        context = ValidationContext(entities=[first, second], tables=[], cells_by_table={})
        findings = self.rule.evaluate(context)
        assert len(findings) == 1
        assert findings[0].entity_id == second.id

    def test_non_numeric_entity_types_are_ignored(self) -> None:
        first = make_entity(entity_type=EntityType.COMMODITY, raw_value="Brent", page_number=1)
        second = make_entity(entity_type=EntityType.COMMODITY, raw_value="Brent", page_number=1)
        context = ValidationContext(entities=[first, second], tables=[], cells_by_table={})
        assert self.rule.evaluate(context) == []


class TestInconsistentTotalsRule:
    rule = InconsistentTotalsRule()

    def test_matching_total_produces_no_findings(self) -> None:
        table = make_table()
        cells = [
            make_cell(table_id=table.id, row=0, column=0, raw_value="Grade A"),
            make_cell(table_id=table.id, row=0, column=1, raw_value="10"),
            make_cell(table_id=table.id, row=1, column=0, raw_value="Grade B"),
            make_cell(table_id=table.id, row=1, column=1, raw_value="20"),
            make_cell(table_id=table.id, row=2, column=0, raw_value="Total"),
            make_cell(table_id=table.id, row=2, column=1, raw_value="30"),
        ]
        context = ValidationContext(entities=[], tables=[table], cells_by_table={table.id: cells})
        assert self.rule.evaluate(context) == []

    def test_mismatched_total_is_flagged(self) -> None:
        table = make_table()
        cells = [
            make_cell(table_id=table.id, row=0, column=0, raw_value="Grade A"),
            make_cell(table_id=table.id, row=0, column=1, raw_value="10"),
            make_cell(table_id=table.id, row=1, column=0, raw_value="Grade B"),
            make_cell(table_id=table.id, row=1, column=1, raw_value="20"),
            make_cell(table_id=table.id, row=2, column=0, raw_value="Total"),
            make_cell(table_id=table.id, row=2, column=1, raw_value="999"),
        ]
        context = ValidationContext(entities=[], tables=[table], cells_by_table={table.id: cells})
        findings = self.rule.evaluate(context)
        assert len(findings) == 1
        assert findings[0].entity_id is None
        assert not findings[0].passed

    def test_table_without_a_total_row_is_skipped(self) -> None:
        table = make_table()
        cells = [
            make_cell(table_id=table.id, row=0, column=0, raw_value="Grade A"),
            make_cell(table_id=table.id, row=0, column=1, raw_value="10"),
        ]
        context = ValidationContext(entities=[], tables=[table], cells_by_table={table.id: cells})
        assert self.rule.evaluate(context) == []

    def test_within_rounding_tolerance_is_not_flagged(self) -> None:
        table = make_table()
        cells = [
            make_cell(table_id=table.id, row=0, column=0, raw_value="Grade A"),
            make_cell(table_id=table.id, row=0, column=1, raw_value="10.001"),
            make_cell(table_id=table.id, row=1, column=0, raw_value="Sum"),
            make_cell(table_id=table.id, row=1, column=1, raw_value="10.0"),
        ]
        context = ValidationContext(entities=[], tables=[table], cells_by_table={table.id: cells})
        assert self.rule.evaluate(context) == []
