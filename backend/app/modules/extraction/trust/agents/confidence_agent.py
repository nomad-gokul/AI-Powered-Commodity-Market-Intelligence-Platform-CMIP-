"""ConfidenceAgent: computes an 8-dimension confidence breakdown per
entity. Deterministic, no LLM call - trust is computed from data this
pipeline and Phase 3.2 already produced, never guessed by asking a model
"how confident are you."

Runs after ValidationAgent and NormalizationAgent within the same
SequentialEngine execution (see pipeline.py) and reads their output
straight off context.state - the blackboard pattern Phase 3.2 already
established - rather than re-querying the database for what a sibling
step in the same run just computed. Entities/tables themselves (Phase
3.2's own persisted output) are fetched independently via repositories,
same as every other trust agent.
"""

import uuid

from shared.agent_contracts import AgentContext

from app.modules.extraction.models import ExtractedEntity, ExtractedTable, ExtractionRun
from app.modules.extraction.repository import ExtractedEntityRepository, ExtractedTableRepository
from app.modules.extraction.trust.agents.schemas import (
    ConfidenceAgentOutput,
    EntityConfidence,
    NormalizationAgentOutput,
    ValidationAgentOutput,
)
from app.modules.extraction.trust.domain import SEVERITY_WEIGHTS, clamp, weighted_average
from app.modules.extraction.trust.models import ValidationCategory
from app.modules.extraction.trust.rules.types import ValidationFinding

# Calibratable priors, not measured accuracy - a starting point product
# can tune as real outcome data (human-review overturn rates per
# provider) accumulates. Unknown providers default to 0.8.
_PROVIDER_RELIABILITY: dict[str, float] = {
    "groq": 0.85,
    "claude": 0.95,
    "openai": 0.93,
    "ollama": 0.75,
}
_DEFAULT_PROVIDER_RELIABILITY = 0.8

_UNGROUNDED_GEOMETRY_SCORE = 0.4
_NO_LAYOUT_DATA_SCORE = 0.85
_MULTI_COLUMN_LAYOUT_SCORE = 0.75
_SINGLE_COLUMN_LAYOUT_SCORE = 1.0

_CONSISTENCY_CATEGORIES = frozenset(
    {ValidationCategory.DUPLICATE, ValidationCategory.CONFLICT, ValidationCategory.CONSISTENCY}
)

_DIMENSION_WEIGHTS: dict[str, float] = {
    "extraction": 0.20,
    "geometry": 0.10,
    "layout": 0.05,
    "table": 0.05,
    "validation": 0.25,
    "consistency": 0.10,
    "normalization": 0.15,
    "provider": 0.10,
}


class ConfidenceAgent:
    def __init__(
        self,
        *,
        extraction_run_id: uuid.UUID,
        extraction_run: ExtractionRun,
        entity_repo: ExtractedEntityRepository,
        table_repo: ExtractedTableRepository,
    ) -> None:
        self._extraction_run_id = extraction_run_id
        self._extraction_run = extraction_run
        self._entity_repo = entity_repo
        self._table_repo = table_repo

    @property
    def name(self) -> str:
        return "confidence"

    async def run(self, context: AgentContext) -> ConfidenceAgentOutput:
        entities = await self._entity_repo.list_all_for_run(self._extraction_run_id)
        tables = await self._table_repo.list_for_run(self._extraction_run_id)

        validation_output = context.state.get("validation")
        findings = (
            validation_output.findings
            if isinstance(validation_output, ValidationAgentOutput)
            else []
        )
        findings_by_entity = self._group_findings(findings)

        normalization_output = context.state.get("normalization")
        normalization_by_entity = (
            {o.entity_id: o for o in normalization_output.outcomes}
            if isinstance(normalization_output, NormalizationAgentOutput)
            else {}
        )

        table_confidence_by_page = self._average_table_confidence_by_page(tables)
        layout_summary = self._extraction_run.metadata_json.get("layout_summary", {})
        provider_score = _PROVIDER_RELIABILITY.get(
            self._extraction_run.provider, _DEFAULT_PROVIDER_RELIABILITY
        )

        scores = [
            self._score_entity(
                entity,
                own_findings=findings_by_entity.get(entity.id, []),
                normalization_confidence=(
                    normalization_by_entity[entity.id].confidence
                    if entity.id in normalization_by_entity
                    else 0.0
                ),
                table_confidence_by_page=table_confidence_by_page,
                layout_summary=layout_summary,
                provider_score=provider_score,
            )
            for entity in entities
        ]
        return ConfidenceAgentOutput(scores=scores)

    def _score_entity(
        self,
        entity: ExtractedEntity,
        *,
        own_findings: list[ValidationFinding],
        normalization_confidence: float,
        table_confidence_by_page: dict[int, float],
        layout_summary: dict[str, object],
        provider_score: float,
    ) -> EntityConfidence:
        extraction_score = clamp(entity.confidence)
        geometry_score = 1.0 if entity.bounding_box is not None else _UNGROUNDED_GEOMETRY_SCORE
        layout_score = self._layout_score(entity.page_number, layout_summary)
        table_score = (
            table_confidence_by_page.get(entity.page_number, 1.0)
            if entity.page_number is not None
            else 1.0
        )
        validation_score = self._weighted_pass_ratio(
            [f for f in own_findings if f.validation_type not in _CONSISTENCY_CATEGORIES]
        )
        consistency_score = self._weighted_pass_ratio(
            [f for f in own_findings if f.validation_type in _CONSISTENCY_CATEGORIES]
        )
        normalization_score = clamp(normalization_confidence)

        components = {
            "extraction": extraction_score,
            "geometry": geometry_score,
            "layout": layout_score,
            "table": table_score,
            "validation": validation_score,
            "consistency": consistency_score,
            "normalization": normalization_score,
            "provider": provider_score,
        }
        overall_score = clamp(weighted_average(components, _DIMENSION_WEIGHTS))

        return EntityConfidence(
            entity_id=entity.id,
            overall_score=overall_score,
            extraction_score=extraction_score,
            geometry_score=geometry_score,
            layout_score=layout_score,
            table_score=table_score,
            consistency_score=consistency_score,
            normalization_score=normalization_score,
            validation_score=validation_score,
            provider_score=provider_score,
            explanation={
                "weights": _DIMENSION_WEIGHTS,
                "components": components,
                "validation_findings": len(own_findings),
            },
        )

    @staticmethod
    def _group_findings(
        findings: list[ValidationFinding],
    ) -> dict[uuid.UUID, list[ValidationFinding]]:
        grouped: dict[uuid.UUID, list[ValidationFinding]] = {}
        for finding in findings:
            if finding.entity_id is None:
                continue
            grouped.setdefault(finding.entity_id, []).append(finding)
        return grouped

    @staticmethod
    def _weighted_pass_ratio(findings: list[ValidationFinding]) -> float:
        if not findings:
            return 1.0
        total_weight = sum(SEVERITY_WEIGHTS[f.severity.value] for f in findings)
        passed_weight = sum(SEVERITY_WEIGHTS[f.severity.value] for f in findings if f.passed)
        if total_weight == 0:
            return 1.0
        return passed_weight / total_weight

    @staticmethod
    def _average_table_confidence_by_page(tables: list[ExtractedTable]) -> dict[int, float]:
        by_page: dict[int, list[float]] = {}
        for table in tables:
            by_page.setdefault(table.page_number, []).append(table.confidence)
        return {page: sum(values) / len(values) for page, values in by_page.items()}

    @staticmethod
    def _layout_score(page_number: int | None, layout_summary: dict[str, object]) -> float:
        if page_number is None:
            return _NO_LAYOUT_DATA_SCORE
        page_info = layout_summary.get(str(page_number))
        if not isinstance(page_info, dict):
            return _NO_LAYOUT_DATA_SCORE
        is_multi_column = page_info.get("is_multi_column")
        if is_multi_column is True:
            return _MULTI_COLUMN_LAYOUT_SCORE
        if is_multi_column is False:
            return _SINGLE_COLUMN_LAYOUT_SCORE
        return _NO_LAYOUT_DATA_SCORE
