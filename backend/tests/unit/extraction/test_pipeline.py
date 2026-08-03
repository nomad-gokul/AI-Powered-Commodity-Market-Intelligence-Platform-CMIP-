"""Unit tests for build_extraction_pipeline: correct step order, correct
agent types, and the documented retry-policy split (single-call agents
retry at the engine level, looping agents don't)."""

import uuid
from unittest.mock import AsyncMock

from app.ai.engine.types import AgentContext
from app.modules.extraction.agents.document_understanding_agent import DocumentUnderstandingAgent
from app.modules.extraction.agents.entity_extraction_agent import EntityExtractionAgent
from app.modules.extraction.agents.layout_agent import LayoutAgent
from app.modules.extraction.agents.persist_results_agent import PersistResultsAgent
from app.modules.extraction.agents.table_extraction_agent import TableExtractionAgent
from app.modules.extraction.pipeline import build_extraction_pipeline
from app.modules.extraction.prompts import get_extraction_prompt_registry

from .agents._doubles import ScriptedStructuredOutputService


def _build_steps() -> list:
    return build_extraction_pipeline(
        extraction_run_id=uuid.uuid4(),
        chunks=[],
        pdf_bytes=b"",
        structured_output_service=ScriptedStructuredOutputService([]),  # type: ignore[arg-type]
        prompt_registry=get_extraction_prompt_registry(),
        provider="groq",
        model="test-model",
        entity_repo=AsyncMock(),
        mention_repo=AsyncMock(),
        table_repo=AsyncMock(),
        cell_repo=AsyncMock(),
    )


class TestBuildExtractionPipeline:
    def test_returns_five_steps_in_pipeline_order(self) -> None:
        steps = _build_steps()
        assert [type(step.agent) for step in steps] == [
            DocumentUnderstandingAgent,
            LayoutAgent,
            EntityExtractionAgent,
            TableExtractionAgent,
            PersistResultsAgent,
        ]

    def test_step_names_match_agent_names(self) -> None:
        steps = _build_steps()
        assert [step.agent.name for step in steps] == [
            "document_understanding",
            "layout",
            "entity_extraction",
            "table_extraction",
            "persist_results",
        ]

    def test_single_call_agents_have_retry_enabled(self) -> None:
        steps = _build_steps()
        document_understanding_step, layout_step = steps[0], steps[1]
        assert document_understanding_step.retry_policy.max_attempts > 1
        assert layout_step.retry_policy.max_attempts > 1

    def test_looping_agents_have_no_engine_level_retry(self) -> None:
        steps = _build_steps()
        entity_step, table_step = steps[2], steps[3]
        assert entity_step.retry_policy.max_attempts == 1
        assert table_step.retry_policy.max_attempts == 1

    def test_persist_results_is_idempotent_so_retry_is_enabled(self) -> None:
        steps = _build_steps()
        persist_step = steps[4]
        assert persist_step.retry_policy.max_attempts > 1

    async def test_persist_results_agent_is_wired_to_the_given_extraction_run_id(self) -> None:
        run_id = uuid.uuid4()
        entity_repo = AsyncMock()
        entity_repo.bulk_create.side_effect = lambda rows: rows
        table_repo = AsyncMock()
        table_repo.bulk_create.side_effect = lambda rows: rows
        steps = build_extraction_pipeline(
            extraction_run_id=run_id,
            chunks=[],
            pdf_bytes=b"",
            structured_output_service=ScriptedStructuredOutputService([]),  # type: ignore[arg-type]
            prompt_registry=get_extraction_prompt_registry(),
            provider="groq",
            model="test-model",
            entity_repo=entity_repo,
            mention_repo=AsyncMock(),
            table_repo=table_repo,
            cell_repo=AsyncMock(),
        )
        persist_agent = steps[4].agent
        assert isinstance(persist_agent, PersistResultsAgent)

        await persist_agent.run(AgentContext(correlation_id="test"))

        entity_repo.delete_for_run.assert_awaited_once_with(run_id)
        table_repo.delete_for_run.assert_awaited_once_with(run_id)
