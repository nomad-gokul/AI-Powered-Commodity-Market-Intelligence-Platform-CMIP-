"""Unit tests for PersistResultsAgent against mocked repositories -
real-database persistence correctness is covered by the integration
suite; this tests the agent's own ORM-row-building and idempotency logic."""

import uuid
from unittest.mock import AsyncMock

import pytest

from app.ai.engine.types import AgentContext
from app.modules.documents.models import DocumentChunk
from app.modules.extraction.agents.persist_results_agent import PersistResultsAgent
from app.modules.extraction.agents.schemas import (
    BoundingBoxModel,
    EntityExtractionAgentOutput,
    GroundedCell,
    GroundedEntity,
    GroundedTable,
    TableExtractionAgentOutput,
)
from app.modules.extraction.models import EntityType, ExtractedEntity, ExtractedTable

Repos = dict[str, AsyncMock]


def _context(**state: object) -> AgentContext:
    context = AgentContext(correlation_id="test-correlation")
    context.state.update(state)
    return context


@pytest.fixture
def repos() -> Repos:
    entity_repo = AsyncMock()
    entity_repo.bulk_create.side_effect = lambda rows: [_with_id(r) for r in rows]
    table_repo = AsyncMock()
    table_repo.bulk_create.side_effect = lambda rows: [_with_id(r) for r in rows]
    mention_repo = AsyncMock()
    cell_repo = AsyncMock()
    return {
        "entity_repo": entity_repo,
        "mention_repo": mention_repo,
        "table_repo": table_repo,
        "cell_repo": cell_repo,
    }


def _with_id(row: ExtractedEntity | ExtractedTable) -> ExtractedEntity | ExtractedTable:
    row.id = uuid.uuid4()
    return row


def _agent(
    repos: Repos, *, chunks: list[DocumentChunk] | None = None
) -> PersistResultsAgent:
    return PersistResultsAgent(
        extraction_run_id=uuid.uuid4(),
        entity_repo=repos["entity_repo"],
        mention_repo=repos["mention_repo"],
        table_repo=repos["table_repo"],
        cell_repo=repos["cell_repo"],
        chunks=chunks or [],
        provider="groq",
        model="test-model",
        entity_prompt_version="1.0",
        table_prompt_version="1.0",
    )


class TestRun:
    async def test_deletes_before_inserting_for_idempotency(self, repos: Repos) -> None:
        agent = _agent(repos)
        await agent.run(_context())

        repos["entity_repo"].delete_for_run.assert_awaited_once()
        repos["table_repo"].delete_for_run.assert_awaited_once()

    async def test_persists_entities_and_their_mentions(self, repos: Repos) -> None:
        chunk = DocumentChunk(
            id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            chunk_index=0,
            page_number=1,
            text="Brent crude rose today.",
            token_count=5,
            metadata_json={},
        )
        entity_output = EntityExtractionAgentOutput(
            entities=[
                GroundedEntity(
                    entity_type=EntityType.COMMODITY,
                    raw_value="Brent",
                    normalized_value="Brent crude",
                    confidence=0.9,
                    page_number=1,
                    bounding_box=BoundingBoxModel(x0=1, y0=2, x1=3, y1=4),
                    source_chunk_id=chunk.id,
                )
            ]
        )
        agent = _agent(repos, chunks=[chunk])

        result = await agent.run(_context(entity_extraction=entity_output))

        assert result.entities_persisted == 1
        repos["entity_repo"].bulk_create.assert_awaited_once()
        persisted_entities = repos["entity_repo"].bulk_create.await_args.args[0]
        assert persisted_entities[0].raw_value == "Brent"
        assert persisted_entities[0].bounding_box == {"x0": 1.0, "y0": 2.0, "x1": 3.0, "y1": 4.0}

        repos["mention_repo"].bulk_create.assert_awaited_once()
        persisted_mentions = repos["mention_repo"].bulk_create.await_args.args[0]
        assert persisted_mentions[0].surrounding_text  # found via find_mention_context
        assert "Brent" in persisted_mentions[0].surrounding_text

    async def test_no_entity_extraction_output_persists_nothing(self, repos: Repos) -> None:
        agent = _agent(repos)
        result = await agent.run(_context())

        assert result.entities_persisted == 0
        repos["entity_repo"].bulk_create.assert_not_awaited()

    async def test_persists_tables_and_cells(self, repos: Repos) -> None:
        table_output = TableExtractionAgentOutput(
            tables=[
                GroundedTable(
                    page_number=1,
                    title="Prices",
                    confidence=0.9,
                    row_count=1,
                    column_count=2,
                    bounding_box=None,
                    cells=[
                        GroundedCell(
                            row=0, column=0, raw_value="Brent", normalized_value="Brent",
                            confidence=0.9, bounding_box=None,
                        ),
                        GroundedCell(
                            row=0, column=1, raw_value="82.14", normalized_value="82.14",
                            confidence=0.9, bounding_box=None,
                        ),
                    ],
                )
            ]
        )
        agent = _agent(repos)

        result = await agent.run(_context(table_extraction=table_output))

        assert result.tables_persisted == 1
        assert result.cells_persisted == 2
        repos["table_repo"].bulk_create.assert_awaited_once()
        repos["cell_repo"].bulk_create.assert_awaited_once()

    async def test_no_table_extraction_output_persists_nothing(self, repos: Repos) -> None:
        agent = _agent(repos)
        result = await agent.run(_context())

        assert result.tables_persisted == 0
        assert result.cells_persisted == 0
        repos["table_repo"].bulk_create.assert_not_awaited()

    def test_name_is_stable(self, repos: Repos) -> None:
        assert _agent(repos).name == "persist_results"
