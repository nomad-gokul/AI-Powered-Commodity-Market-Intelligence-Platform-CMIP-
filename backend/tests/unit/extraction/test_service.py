"""Unit tests for ExtractionService against mocked repositories."""

import uuid
from unittest.mock import AsyncMock, Mock

import pytest
from ai_service.prompts.registry import PromptRegistry
from shared.prompt_contracts import PromptMetadata, PromptPackage, PromptVersion

from app.core.exceptions import ConflictError, NotFoundError
from app.modules.extraction.models import ExtractionRun, ExtractionStatus
from app.modules.extraction.service import ExtractionService


def _document(sha256_hash: str = "a" * 64) -> Mock:
    return Mock(sha256_hash=sha256_hash)


def _prompt_registry() -> PromptRegistry:
    registry = PromptRegistry()
    registry.register(
        PromptPackage(
            name="document_understanding",
            version=PromptVersion(major=1),
            system_prompt="sys",
            user_prompt_template="template",
            metadata=PromptMetadata(),
        )
    )
    return registry


def _service(**overrides: object) -> tuple[ExtractionService, dict[str, AsyncMock]]:
    mocks = {
        "document_repo": AsyncMock(),
        "chunk_repo": AsyncMock(),
        "run_repo": AsyncMock(),
        "entity_repo": AsyncMock(),
        "table_repo": AsyncMock(),
        "cell_repo": AsyncMock(),
        "audit_service": AsyncMock(),
        "job_queue": AsyncMock(),
    }
    mocks.update(overrides)  # type: ignore[arg-type]
    mocks["run_repo"].find_completed_by_fingerprint.return_value = None
    service = ExtractionService(
        document_repo=mocks["document_repo"],
        chunk_repo=mocks["chunk_repo"],
        run_repo=mocks["run_repo"],
        entity_repo=mocks["entity_repo"],
        table_repo=mocks["table_repo"],
        cell_repo=mocks["cell_repo"],
        audit_service=mocks["audit_service"],
        job_queue=mocks["job_queue"],
        prompt_registry=_prompt_registry(),
        provider="groq",
        model="test-model",
    )
    return service, mocks


class TestTriggerExtraction:
    async def test_creates_run_and_enqueues_job(self) -> None:
        service, mocks = _service()
        mocks["document_repo"].get_active_by_id.return_value = _document()
        mocks["run_repo"].list_for_document.return_value = []
        mocks["chunk_repo"].count_for_document.return_value = 5
        mocks["run_repo"].create.side_effect = lambda run: run

        document_id = uuid.uuid4()
        run = await service.trigger_extraction(document_id, requested_by=uuid.uuid4())

        assert run.status == ExtractionStatus.PENDING
        assert run.pipeline_version
        assert run.prompt_version == "1.0"
        mocks["job_queue"].enqueue_job.assert_awaited_once()
        args = mocks["job_queue"].enqueue_job.await_args.args
        assert args[0] == "run_extraction"

    async def test_missing_document_raises_not_found(self) -> None:
        service, mocks = _service()
        mocks["document_repo"].get_active_by_id.return_value = None

        with pytest.raises(NotFoundError):
            await service.trigger_extraction(uuid.uuid4(), requested_by=uuid.uuid4())

    async def test_active_run_already_in_progress_raises_conflict(self) -> None:
        service, mocks = _service()
        mocks["document_repo"].get_active_by_id.return_value = _document()
        mocks["run_repo"].list_for_document.return_value = [
            ExtractionRun(status=ExtractionStatus.RUNNING)
        ]

        with pytest.raises(ConflictError):
            await service.trigger_extraction(uuid.uuid4(), requested_by=uuid.uuid4())

    async def test_no_chunks_yet_raises_conflict(self) -> None:
        service, mocks = _service()
        mocks["document_repo"].get_active_by_id.return_value = _document()
        mocks["run_repo"].list_for_document.return_value = []
        mocks["chunk_repo"].count_for_document.return_value = 0

        with pytest.raises(ConflictError):
            await service.trigger_extraction(uuid.uuid4(), requested_by=uuid.uuid4())

    async def test_completed_prior_run_does_not_block_a_new_one(self) -> None:
        service, mocks = _service()
        mocks["document_repo"].get_active_by_id.return_value = _document()
        mocks["run_repo"].list_for_document.return_value = [
            ExtractionRun(status=ExtractionStatus.COMPLETED)
        ]
        mocks["chunk_repo"].count_for_document.return_value = 5
        mocks["run_repo"].create.side_effect = lambda run: run

        run = await service.trigger_extraction(uuid.uuid4(), requested_by=uuid.uuid4())
        assert run.status == ExtractionStatus.PENDING

    async def test_identical_fingerprint_returns_existing_run_without_enqueueing(self) -> None:
        service, mocks = _service()
        mocks["document_repo"].get_active_by_id.return_value = _document()
        mocks["run_repo"].list_for_document.return_value = []
        mocks["chunk_repo"].count_for_document.return_value = 5
        existing_run = ExtractionRun(status=ExtractionStatus.COMPLETED)
        mocks["run_repo"].find_completed_by_fingerprint.return_value = existing_run

        run = await service.trigger_extraction(uuid.uuid4(), requested_by=uuid.uuid4())

        assert run is existing_run
        mocks["run_repo"].create.assert_not_called()
        mocks["job_queue"].enqueue_job.assert_not_awaited()

    async def test_new_run_is_created_with_a_fingerprint_set(self) -> None:
        service, mocks = _service()
        mocks["document_repo"].get_active_by_id.return_value = _document()
        mocks["run_repo"].list_for_document.return_value = []
        mocks["chunk_repo"].count_for_document.return_value = 5
        mocks["run_repo"].create.side_effect = lambda run: run

        run = await service.trigger_extraction(uuid.uuid4(), requested_by=uuid.uuid4())

        assert run.extraction_fingerprint is not None
        assert len(run.extraction_fingerprint) == 64

    async def test_different_document_hash_yields_a_different_fingerprint(self) -> None:
        service, mocks = _service()
        mocks["run_repo"].list_for_document.return_value = []
        mocks["chunk_repo"].count_for_document.return_value = 5
        mocks["run_repo"].create.side_effect = lambda run: run

        mocks["document_repo"].get_active_by_id.return_value = _document("a" * 64)
        run_a = await service.trigger_extraction(uuid.uuid4(), requested_by=uuid.uuid4())

        mocks["document_repo"].get_active_by_id.return_value = _document("b" * 64)
        run_b = await service.trigger_extraction(uuid.uuid4(), requested_by=uuid.uuid4())

        assert run_a.extraction_fingerprint != run_b.extraction_fingerprint


class TestGetRun:
    async def test_returns_run(self) -> None:
        service, mocks = _service()
        expected = ExtractionRun()
        mocks["run_repo"].get_by_id.return_value = expected

        assert await service.get_run(uuid.uuid4()) is expected

    async def test_missing_run_raises_not_found(self) -> None:
        service, mocks = _service()
        mocks["run_repo"].get_by_id.return_value = None

        with pytest.raises(NotFoundError):
            await service.get_run(uuid.uuid4())


class TestListEntitiesAndTables:
    async def test_list_entities_returns_items_and_true_total(self) -> None:
        service, mocks = _service()
        mocks["entity_repo"].list_for_document.return_value = ["a", "b"]
        mocks["entity_repo"].count_for_document.return_value = 42

        items, total = await service.list_entities(uuid.uuid4())
        assert items == ["a", "b"]
        assert total == 42

    async def test_list_tables_returns_items_and_true_total(self) -> None:
        service, mocks = _service()
        mocks["table_repo"].list_for_document.return_value = ["t1"]
        mocks["table_repo"].count_for_document.return_value = 7

        items, total = await service.list_tables(uuid.uuid4())
        assert items == ["t1"]
        assert total == 7


class TestGetTableAndCells:
    async def test_get_table_returns_table(self) -> None:
        service, mocks = _service()
        expected = object()
        mocks["table_repo"].get_by_id.return_value = expected

        assert await service.get_table(uuid.uuid4()) is expected

    async def test_get_table_missing_raises_not_found(self) -> None:
        service, mocks = _service()
        mocks["table_repo"].get_by_id.return_value = None

        with pytest.raises(NotFoundError):
            await service.get_table(uuid.uuid4())

    async def test_list_cells_delegates_to_repo(self) -> None:
        service, mocks = _service()
        mocks["cell_repo"].list_for_table.return_value = ["cell1", "cell2"]

        assert await service.list_cells(uuid.uuid4()) == ["cell1", "cell2"]
