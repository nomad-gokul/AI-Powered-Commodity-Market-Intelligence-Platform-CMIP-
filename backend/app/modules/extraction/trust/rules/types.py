"""Shared types for validation rules and the registry.

Two rule shapes: EntityValidationRule evaluates one entity in isolation
(most checks - a date, a currency code, a quantity). CrossEntityValidationRule
evaluates everything an extraction run produced together (duplicates,
conflicting values, table-total reconciliation) - a finding that can't be
attributed to a single entity carries entity_id=None on the resulting
ValidationFinding rather than being forced onto an arbitrary one.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from app.modules.extraction.models import EntityType, ExtractedEntity, ExtractedTable, TableCell
from app.modules.extraction.trust.models import ValidationCategory, ValidationSeverity


@dataclass(frozen=True, slots=True)
class ValidationFinding:
    entity_id: uuid.UUID | None
    rule_id: str
    validation_type: ValidationCategory
    severity: ValidationSeverity
    passed: bool
    message: str


class EntityValidationRule(Protocol):
    rule_id: str
    validation_type: ValidationCategory
    applies_to: frozenset[EntityType]

    def evaluate(self, entity: ExtractedEntity) -> ValidationFinding | None:
        """Return None if the rule has nothing to say about this entity -
        e.g. its raw_value doesn't look like a number at all, so an
        impossible-quantity check can't meaningfully apply."""
        ...


@dataclass(frozen=True, slots=True)
class ValidationContext:
    """Everything one extraction run produced, handed to every
    cross-entity rule at once - the only way a rule like "does this
    table's stated total match the sum of its rows" can be evaluated."""

    entities: Sequence[ExtractedEntity]
    tables: Sequence[ExtractedTable]
    cells_by_table: dict[uuid.UUID, list[TableCell]]


class CrossEntityValidationRule(Protocol):
    rule_id: str
    validation_type: ValidationCategory

    def evaluate(self, context: ValidationContext) -> list[ValidationFinding]: ...
