"""Unit tests for build_trust_pipeline: correct step order and agent
types for the Validation -> Normalization -> Confidence -> Review Queue
-> Persist sequence (deliberately NOT the spec's literal Validation ->
Confidence -> Normalization order - see pipeline.py's docstring)."""

import uuid
from unittest.mock import AsyncMock

from app.modules.extraction.models import ExtractionRun, ExtractionStatus
from app.modules.extraction.trust.agents.confidence_agent import ConfidenceAgent
from app.modules.extraction.trust.agents.normalization_agent import NormalizationAgent
from app.modules.extraction.trust.agents.persist_trust_results_agent import (
    PersistTrustResultsAgent,
)
from app.modules.extraction.trust.agents.review_queue_agent import ReviewQueueAgent
from app.modules.extraction.trust.agents.validation_agent import ValidationAgent
from app.modules.extraction.trust.normalization.loader import get_canonical_registries
from app.modules.extraction.trust.pipeline import build_trust_pipeline
from app.modules.extraction.trust.rules.builtin import get_validation_rule_registry


def _build_steps() -> list:
    run_id = uuid.uuid4()
    extraction_run = ExtractionRun(
        id=run_id,
        document_id=uuid.uuid4(),
        pipeline_version="3.2.0",
        provider="groq",
        model="test-model",
        prompt_version="1.0",
        prompt_hash="hash",
        status=ExtractionStatus.COMPLETED,
        metadata_json={},
    )
    return build_trust_pipeline(
        extraction_run_id=run_id,
        extraction_run=extraction_run,
        entity_repo=AsyncMock(),
        table_repo=AsyncMock(),
        cell_repo=AsyncMock(),
        validation_repo=AsyncMock(),
        confidence_repo=AsyncMock(),
        normalization_repo=AsyncMock(),
        review_queue_repo=AsyncMock(),
        rule_registry=get_validation_rule_registry(),
        canonical_registries=get_canonical_registries(),
    )


class TestBuildTrustPipeline:
    def test_returns_five_steps_in_pipeline_order(self) -> None:
        steps = _build_steps()
        assert [type(step.agent) for step in steps] == [
            ValidationAgent,
            NormalizationAgent,
            ConfidenceAgent,
            ReviewQueueAgent,
            PersistTrustResultsAgent,
        ]

    def test_step_names_match_agent_names(self) -> None:
        steps = _build_steps()
        assert [step.agent.name for step in steps] == [
            "validation",
            "normalization",
            "confidence",
            "review_queue",
            "persist_trust_results",
        ]

    def test_every_step_has_retry_enabled(self) -> None:
        # Unlike Phase 3.2's extraction pipeline, every step here is
        # deterministic (no LLM call), so there is no cheap-vs-expensive
        # retry distinction to make - every step gets the same policy.
        steps = _build_steps()
        for step in steps:
            assert step.retry_policy.max_attempts > 1
