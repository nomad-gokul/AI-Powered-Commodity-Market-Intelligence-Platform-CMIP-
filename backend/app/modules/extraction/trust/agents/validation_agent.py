"""ValidationAgent: runs every registered rule - entity-scoped and
cross-entity - against one extraction run's already-persisted entities
and tables. Deterministic, no LLM call (see docs/ARCHITECTURE.md's Phase
3.3 section for why).

Reads straight from the database via the repositories it's given: this
pipeline is its own later job (POST /extraction-runs/{id}/validate), not
appended in-memory to extraction's SequentialEngine run, so there is no
context.state carrying Phase 3.2's agent outputs to read from - the
extraction run's own persisted rows are the only interface between the
two pipelines.
"""

import uuid

from shared.agent_contracts import AgentContext

from app.modules.extraction.repository import (
    ExtractedEntityRepository,
    ExtractedTableRepository,
    TableCellRepository,
)
from app.modules.extraction.trust.agents.schemas import ValidationAgentOutput
from app.modules.extraction.trust.rules.registry import ValidationRuleRegistry
from app.modules.extraction.trust.rules.types import ValidationContext, ValidationFinding


class ValidationAgent:
    def __init__(
        self,
        *,
        extraction_run_id: uuid.UUID,
        entity_repo: ExtractedEntityRepository,
        table_repo: ExtractedTableRepository,
        cell_repo: TableCellRepository,
        rule_registry: ValidationRuleRegistry,
    ) -> None:
        self._extraction_run_id = extraction_run_id
        self._entity_repo = entity_repo
        self._table_repo = table_repo
        self._cell_repo = cell_repo
        self._rule_registry = rule_registry

    @property
    def name(self) -> str:
        return "validation"

    async def run(self, context: AgentContext) -> ValidationAgentOutput:
        entities = await self._entity_repo.list_all_for_run(self._extraction_run_id)
        tables = await self._table_repo.list_for_run(self._extraction_run_id)
        cells_by_table = await self._cell_repo.list_for_tables([t.id for t in tables])

        findings: list[ValidationFinding] = []
        for entity in entities:
            for rule in self._rule_registry.entity_rules_for(entity.entity_type):
                finding = rule.evaluate(entity)
                if finding is not None:
                    findings.append(finding)

        validation_context = ValidationContext(
            entities=entities, tables=tables, cells_by_table=cells_by_table
        )
        for cross_rule in self._rule_registry.all_cross_entity_rules():
            findings.extend(cross_rule.evaluate(validation_context))

        return ValidationAgentOutput(findings=findings)
