"""Unit tests for GraphBuilderService against mocked repositories.

build_for_extraction_run's SequentialEngine-driven success path is
covered by the integration suite (it genuinely needs the real pipeline
running against real trusted data); here we cover its own guard clause
and build_all's aggregation/partial-failure control flow in isolation,
by stubbing build_for_extraction_run itself.
"""

import uuid
from unittest.mock import AsyncMock

import pytest

from app.core.exceptions import ConflictError
from app.modules.extraction.models import ExtractionStatus
from app.modules.extraction.trust.models import TrustPipelineRun
from app.modules.graph.agents.schemas import PersistGraphResultsOutput
from app.modules.graph.builder_service import (
    GraphBuilderService,
    GraphBuildPartialFailure,
    GraphBuildStats,
)

pytestmark = pytest.mark.asyncio


def _service(**overrides: object) -> tuple[GraphBuilderService, dict[str, AsyncMock]]:
    mocks = {
        "entity_repo": AsyncMock(),
        "mention_repo": AsyncMock(),
        "chunk_repo": AsyncMock(),
        "extraction_run_repo": AsyncMock(),
        "normalization_repo": AsyncMock(),
        "confidence_repo": AsyncMock(),
        "node_repo": AsyncMock(),
        "edge_repo": AsyncMock(),
        "evidence_repo": AsyncMock(),
        "trust_run_repo": AsyncMock(),
        "rule_registry": AsyncMock(),
    }
    mocks.update(overrides)  # type: ignore[arg-type]
    service = GraphBuilderService(
        entity_repo=mocks["entity_repo"],
        mention_repo=mocks["mention_repo"],
        chunk_repo=mocks["chunk_repo"],
        extraction_run_repo=mocks["extraction_run_repo"],
        normalization_repo=mocks["normalization_repo"],
        confidence_repo=mocks["confidence_repo"],
        node_repo=mocks["node_repo"],
        edge_repo=mocks["edge_repo"],
        evidence_repo=mocks["evidence_repo"],
        trust_run_repo=mocks["trust_run_repo"],
        rule_registry=mocks["rule_registry"],
    )
    return service, mocks


def _output(**overrides: int) -> PersistGraphResultsOutput:
    base = {
        "nodes_created": 1,
        "nodes_updated": 0,
        "edges_created": 1,
        "edges_updated": 0,
        "evidence_created": 2,
    }
    base.update(overrides)
    return PersistGraphResultsOutput(**base)  # type: ignore[arg-type]


class TestBuildForExtractionRun:
    async def test_missing_trust_run_raises_conflict(self) -> None:
        service, mocks = _service()
        mocks["trust_run_repo"].latest_for_extraction_run.return_value = None

        with pytest.raises(ConflictError):
            await service.build_for_extraction_run(uuid.uuid4())

    async def test_incomplete_trust_run_raises_conflict(self) -> None:
        service, mocks = _service()
        mocks["trust_run_repo"].latest_for_extraction_run.return_value = TrustPipelineRun(
            status=ExtractionStatus.RUNNING
        )

        with pytest.raises(ConflictError):
            await service.build_for_extraction_run(uuid.uuid4())


class TestBuildAll:
    async def test_aggregates_stats_across_every_completed_run(self) -> None:
        service, mocks = _service()
        run_a, run_b = uuid.uuid4(), uuid.uuid4()
        mocks["trust_run_repo"].list_latest_completed.return_value = [
            TrustPipelineRun(extraction_run_id=run_a, status=ExtractionStatus.COMPLETED),
            TrustPipelineRun(extraction_run_id=run_b, status=ExtractionStatus.COMPLETED),
        ]
        service.build_for_extraction_run = AsyncMock(  # type: ignore[method-assign]
            side_effect=[_output(nodes_created=1), _output(nodes_created=2)]
        )

        stats = await service.build_all()

        assert stats.runs_processed == 2
        assert stats.nodes_created == 3
        assert stats.edges_created == 2

    async def test_no_completed_runs_returns_zeroed_stats(self) -> None:
        service, mocks = _service()
        mocks["trust_run_repo"].list_latest_completed.return_value = []

        stats = await service.build_all()

        assert stats == GraphBuildStats()

    async def test_failure_partway_through_raises_with_partial_stats(self) -> None:
        service, mocks = _service()
        run_a, run_b, run_c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        mocks["trust_run_repo"].list_latest_completed.return_value = [
            TrustPipelineRun(extraction_run_id=run_a, status=ExtractionStatus.COMPLETED),
            TrustPipelineRun(extraction_run_id=run_b, status=ExtractionStatus.COMPLETED),
            TrustPipelineRun(extraction_run_id=run_c, status=ExtractionStatus.COMPLETED),
        ]
        service.build_for_extraction_run = AsyncMock(  # type: ignore[method-assign]
            side_effect=[_output(nodes_created=1), RuntimeError("boom"), _output(nodes_created=99)]
        )

        with pytest.raises(GraphBuildPartialFailure) as exc_info:
            await service.build_all()

        assert exc_info.value.stats.runs_processed == 1
        assert exc_info.value.stats.nodes_created == 1
        assert exc_info.value.failed_extraction_run_id == run_b
