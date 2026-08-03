"""Unit tests for GraphService (the build-run trigger/read lifecycle)
against mocked repositories."""

import uuid
from unittest.mock import AsyncMock

import pytest

from app.core.exceptions import ConflictError, NotFoundError
from app.modules.extraction.models import ExtractionRun
from app.modules.graph.models import GraphBuildRun
from app.modules.graph.service import GraphService

pytestmark = pytest.mark.asyncio


def _service(**overrides: object) -> tuple[GraphService, dict[str, AsyncMock]]:
    mocks = {
        "extraction_run_repo": AsyncMock(),
        "build_run_repo": AsyncMock(),
        "audit_service": AsyncMock(),
        "job_queue": AsyncMock(),
    }
    mocks.update(overrides)  # type: ignore[arg-type]
    service = GraphService(
        extraction_run_repo=mocks["extraction_run_repo"],
        build_run_repo=mocks["build_run_repo"],
        audit_service=mocks["audit_service"],
        job_queue=mocks["job_queue"],
    )
    return service, mocks


class TestTriggerRebuild:
    async def test_full_corpus_rebuild_creates_run_and_enqueues_job(self) -> None:
        service, mocks = _service()
        mocks["build_run_repo"].get_active.return_value = None
        mocks["build_run_repo"].create.side_effect = lambda run: run

        run = await service.trigger_rebuild(extraction_run_id=None, requested_by=uuid.uuid4())

        assert run.extraction_run_id is None
        mocks["extraction_run_repo"].get_by_id.assert_not_awaited()
        mocks["job_queue"].enqueue_job.assert_awaited_once()
        assert mocks["job_queue"].enqueue_job.await_args.args[0] == "run_graph_rebuild"

    async def test_scoped_rebuild_verifies_extraction_run_exists(self) -> None:
        service, mocks = _service()
        run_id = uuid.uuid4()
        mocks["extraction_run_repo"].get_by_id.return_value = ExtractionRun(id=run_id)
        mocks["build_run_repo"].get_active.return_value = None
        mocks["build_run_repo"].create.side_effect = lambda run: run

        run = await service.trigger_rebuild(extraction_run_id=run_id, requested_by=uuid.uuid4())

        assert run.extraction_run_id == run_id

    async def test_missing_extraction_run_raises_not_found(self) -> None:
        service, mocks = _service()
        mocks["extraction_run_repo"].get_by_id.return_value = None

        with pytest.raises(NotFoundError):
            await service.trigger_rebuild(extraction_run_id=uuid.uuid4(), requested_by=uuid.uuid4())

    async def test_active_build_raises_conflict(self) -> None:
        service, mocks = _service()
        mocks["build_run_repo"].get_active.return_value = GraphBuildRun(id=uuid.uuid4())

        with pytest.raises(ConflictError):
            await service.trigger_rebuild(extraction_run_id=None, requested_by=uuid.uuid4())


class TestGetBuildRun:
    async def test_returns_run(self) -> None:
        service, mocks = _service()
        build_run = GraphBuildRun(id=uuid.uuid4())
        mocks["build_run_repo"].get_by_id.return_value = build_run

        assert await service.get_build_run(build_run.id) is build_run

    async def test_missing_raises_not_found(self) -> None:
        service, mocks = _service()
        mocks["build_run_repo"].get_by_id.return_value = None

        with pytest.raises(NotFoundError):
            await service.get_build_run(uuid.uuid4())


class TestListBuildRuns:
    async def test_returns_runs_and_total(self) -> None:
        service, mocks = _service()
        mocks["build_run_repo"].list_recent.return_value = [GraphBuildRun(id=uuid.uuid4())]
        mocks["build_run_repo"].count_recent.return_value = 1

        runs, total = await service.list_build_runs()

        assert len(runs) == 1
        assert total == 1
