"""Cross-entity validation rules: checks that only make sense given the
full set of entities (and, for table totals, tables/cells) an extraction
run produced together - a single entity can't be "a duplicate" or
"conflicting" in isolation.
"""

from collections.abc import Sequence

from app.modules.extraction.models import EntityType, ExtractedEntity, ExtractedTable, TableCell
from app.modules.extraction.trust.domain import parse_numeric, values_equal_within_tolerance
from app.modules.extraction.trust.models import ValidationCategory, ValidationSeverity
from app.modules.extraction.trust.rules.types import ValidationContext, ValidationFinding

_NUMERIC_ENTITY_TYPES = frozenset({EntityType.PRICE, EntityType.QUANTITY})


def _dedup_key(raw_value: str) -> str:
    return " ".join(raw_value.strip().lower().split())


class DuplicateEntityRule:
    """Flags entities that are the same type, same raw text, and the same
    page as an entity already seen - the second and later occurrences are
    almost certainly the same real-world mention extracted twice (e.g.
    once per overlapping chunk), not two distinct facts."""

    rule_id = "entity.duplicate"
    validation_type = ValidationCategory.DUPLICATE

    def evaluate(self, context: ValidationContext) -> list[ValidationFinding]:
        findings: list[ValidationFinding] = []
        seen: dict[tuple[EntityType, int | None, str], ExtractedEntity] = {}
        for entity in context.entities:
            key = (entity.entity_type, entity.page_number, _dedup_key(entity.raw_value))
            first = seen.get(key)
            if first is None:
                seen[key] = entity
                continue
            findings.append(
                ValidationFinding(
                    entity_id=entity.id,
                    rule_id=self.rule_id,
                    validation_type=self.validation_type,
                    severity=ValidationSeverity.WARNING,
                    passed=False,
                    message=(
                        f"Duplicate of entity {first.id}: {entity.entity_type.value} "
                        f"{entity.raw_value!r} on page {entity.page_number}"
                    ),
                )
            )
        return findings


class ConflictingValuesRule:
    """Flags numeric entities (PRICE/QUANTITY) that share the same raw
    text, type, and page as another entity but resolved to a materially
    different numeric value - the same phrase should never normalize to
    two different numbers within one run."""

    rule_id = "entity.conflicting_values"
    validation_type = ValidationCategory.CONFLICT

    def evaluate(self, context: ValidationContext) -> list[ValidationFinding]:
        groups: dict[tuple[EntityType, int | None, str], list[ExtractedEntity]] = {}
        for entity in context.entities:
            if entity.entity_type not in _NUMERIC_ENTITY_TYPES:
                continue
            key = (entity.entity_type, entity.page_number, _dedup_key(entity.raw_value))
            groups.setdefault(key, []).append(entity)

        findings: list[ValidationFinding] = []
        for group in groups.values():
            if len(group) < 2:
                continue
            raw_parsed = [
                (entity, parse_numeric(entity.normalized_value or entity.raw_value))
                for entity in group
            ]
            parsed: list[tuple[ExtractedEntity, float]] = [
                (entity, value) for entity, value in raw_parsed if value is not None
            ]
            if len(parsed) < 2:
                continue
            baseline_entity, baseline_value = parsed[0]
            for entity, value in parsed[1:]:
                if values_equal_within_tolerance(baseline_value, value):
                    continue
                findings.append(
                    ValidationFinding(
                        entity_id=entity.id,
                        rule_id=self.rule_id,
                        validation_type=self.validation_type,
                        severity=ValidationSeverity.WARNING,
                        passed=False,
                        message=(
                            f"Value {value} conflicts with {baseline_value} from entity "
                            f"{baseline_entity.id} (same text {entity.raw_value!r} on page "
                            f"{entity.page_number})"
                        ),
                    )
                )
        return findings


_TOTAL_LABEL_HINTS = ("total", "sum")


class InconsistentTotalsRule:
    """Flags a table whose row-labelled "Total"/"Sum" row doesn't match
    the sum of the other rows in the same column, beyond a small
    tolerance for rounding. Assumes column 0 holds the row label, matching
    how TableExtractionAgent lays out grounded tables."""

    rule_id = "table.inconsistent_totals"
    validation_type = ValidationCategory.CONSISTENCY

    def evaluate(self, context: ValidationContext) -> list[ValidationFinding]:
        findings: list[ValidationFinding] = []
        for table in context.tables:
            findings.extend(self._check_table(table, context.cells_by_table.get(table.id, [])))
        return findings

    def _check_table(
        self, table: ExtractedTable, cells: Sequence[TableCell]
    ) -> list[ValidationFinding]:
        by_row: dict[int, dict[int, TableCell]] = {}
        for cell in cells:
            by_row.setdefault(cell.row, {})[cell.column] = cell

        total_row_index = None
        for row_index, row in by_row.items():
            label_cell = row.get(0)
            if label_cell is not None and label_cell.raw_value and any(
                hint in label_cell.raw_value.lower() for hint in _TOTAL_LABEL_HINTS
            ):
                total_row_index = row_index
                break
        if total_row_index is None:
            return []

        total_row = by_row[total_row_index]
        data_rows = [row for index, row in by_row.items() if index != total_row_index]

        findings: list[ValidationFinding] = []
        for column, total_cell in total_row.items():
            if column == 0:
                continue
            claimed = parse_numeric(total_cell.normalized_value or total_cell.raw_value or "")
            if claimed is None:
                continue
            column_values = [
                value
                for row in data_rows
                if column in row
                and (
                    value := parse_numeric(
                        row[column].normalized_value or row[column].raw_value or ""
                    )
                )
                is not None
            ]
            if not column_values:
                continue
            computed_sum = sum(column_values)
            if values_equal_within_tolerance(claimed, computed_sum, relative_tolerance=0.02):
                continue
            findings.append(
                ValidationFinding(
                    entity_id=None,
                    rule_id=self.rule_id,
                    validation_type=self.validation_type,
                    severity=ValidationSeverity.ERROR,
                    passed=False,
                    message=(
                        f"Table {table.id} column {column}: stated total {claimed} does not "
                        f"match the sum of its rows ({computed_sum})"
                    ),
                )
            )
        return findings
