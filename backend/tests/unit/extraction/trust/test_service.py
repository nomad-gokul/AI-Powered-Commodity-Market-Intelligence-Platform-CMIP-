"""Unit tests for TrustPipelineService against mocked repositories."""

import uuid
from unittest.mock import AsyncMock

import pytest

from app.core.exceptions import ConflictError, NotFoundError
from app.modules.extraction.models import ExtractionRun, ExtractionStatus
from app.modules.extraction.trust.models import ReviewStatus, TrustPipelineRun
from app.modules.extraction.trust.service import TrustPipelineService

pytestmark = pytest.mark.asyncio


def _service(**overrides: object) -> tuple[TrustPipelineService, dict[str, AsyncMock]]:
    mocks = {
        "extraction_run_repo": AsyncMock(),
        "trust_run_repo": AsyncMock(),
        "validation_repo": AsyncMock(),
        "confidence_repo": AsyncMock(),
        "normalization_repo": AsyncMock(),
        "review_queue_repo": AsyncMock(),
        "audit_service": AsyncMock(),
        "job_queue": AsyncMock(),
    }
    mocks.update(overrides)  # type: ignore[arg-type]
    service = TrustPipelineService(
        extraction_run_repo=mocks["extraction_run_repo"],
        trust_run_repo=mocks["trust_run_repo"],
        validation_repo=mocks["validation_repo"],
        confidence_repo=mocks["confidence_repo"],
        normalization_repo=mocks["normalization_repo"],
        review_queue_repo=mocks["review_queue_repo"],
        audit_service=mocks["audit_service"],
        job_queue=mocks["job_queue"],
    )
    return service, mocks


class TestTriggerValidation:
    async def test_creates_run_and_enqueues_job(self) -> None:
        service, mocks = _service()
        mocks["extraction_run_repo"].get_by_id.return_value = ExtractionRun(
            status=ExtractionStatus.COMPLETED
        )
        mocks["trust_run_repo"].latest_for_extraction_run.return_value = None
        mocks["trust_run_repo"].create.side_effect = lambda run: run

        run = await service.trigger_validation(uuid.uuid4(), requested_by=uuid.uuid4())

        assert run.status == ExtractionStatus.PENDING
        mocks["job_queue"].enqueue_job.assert_awaited_once()
        assert mocks["job_queue"].enqueue_job.await_args.args[0] == "run_trust_pipeline"

    async def test_missing_extraction_run_raises_not_found(self) -> None:
        service, mocks = _service()
        mocks["extraction_run_repo"].get_by_id.return_value = None

        with pytest.raises(NotFoundError):
            await service.trigger_validation(uuid.uuid4(), requested_by=uuid.uuid4())

    async def test_extraction_still_running_raises_conflict(self) -> None:
        service, mocks = _service()
        mocks["extraction_run_repo"].get_by_id.return_value = ExtractionRun(
            status=ExtractionStatus.RUNNING
        )

        with pytest.raises(ConflictError):
            await service.trigger_validation(uuid.uuid4(), requested_by=uuid.uuid4())

    async def test_extraction_failed_raises_conflict(self) -> None:
        service, mocks = _service()
        mocks["extraction_run_repo"].get_by_id.return_value = ExtractionRun(
            status=ExtractionStatus.FAILED
        )

        with pytest.raises(ConflictError):
            await service.trigger_validation(uuid.uuid4(), requested_by=uuid.uuid4())

    async def test_trust_run_already_active_raises_conflict(self) -> None:
        service, mocks = _service()
        mocks["extraction_run_repo"].get_by_id.return_value = ExtractionRun(
            status=ExtractionStatus.COMPLETED
        )
        mocks["trust_run_repo"].latest_for_extraction_run.return_value = TrustPipelineRun(
            status=ExtractionStatus.RUNNING
        )

        with pytest.raises(ConflictError):
            await service.trigger_validation(uuid.uuid4(), requested_by=uuid.uuid4())

    async def test_completed_prior_trust_run_does_not_block_a_new_one(self) -> None:
        service, mocks = _service()
        mocks["extraction_run_repo"].get_by_id.return_value = ExtractionRun(
            status=ExtractionStatus.COMPLETED
        )
        mocks["trust_run_repo"].latest_for_extraction_run.return_value = TrustPipelineRun(
            status=ExtractionStatus.COMPLETED
        )
        mocks["trust_run_repo"].create.side_effect = lambda run: run

        run = await service.trigger_validation(uuid.uuid4(), requested_by=uuid.uuid4())
        assert run.status == ExtractionStatus.PENDING


class TestReadResults:
    async def test_get_trust_run_returns_run(self) -> None:
        service, mocks = _service()
        expected = TrustPipelineRun()
        mocks["trust_run_repo"].get_by_id.return_value = expected
        assert await service.get_trust_run(uuid.uuid4()) is expected

    async def test_get_trust_run_missing_raises_not_found(self) -> None:
        service, mocks = _service()
        mocks["trust_run_repo"].get_by_id.return_value = None
        with pytest.raises(NotFoundError):
            await service.get_trust_run(uuid.uuid4())

    async def test_get_confidence_missing_raises_not_found(self) -> None:
        service, mocks = _service()
        mocks["confidence_repo"].get_by_id.return_value = None
        with pytest.raises(NotFoundError):
            await service.get_confidence(uuid.uuid4())

    async def test_get_normalization_missing_raises_not_found(self) -> None:
        service, mocks = _service()
        mocks["normalization_repo"].get_by_id.return_value = None
        with pytest.raises(NotFoundError):
            await service.get_normalization(uuid.uuid4())

    async def test_list_validation_results_returns_items_and_true_total(self) -> None:
        service, mocks = _service()
        mocks["validation_repo"].list_for_run.return_value = ["a", "b"]
        mocks["validation_repo"].count_for_run.return_value = 20
        items, total = await service.list_validation_results(uuid.uuid4())
        assert items == ["a", "b"]
        assert total == 20


class TestReviewQueue:
    async def test_list_review_queue_returns_items_and_true_total(self) -> None:
        service, mocks = _service()
        mocks["review_queue_repo"].list_queue.return_value = ["r1"]
        mocks["review_queue_repo"].count_queue.return_value = 3
        items, total = await service.list_review_queue()
        assert items == ["r1"]
        assert total == 3

    async def test_get_review_item_missing_raises_not_found(self) -> None:
        service, mocks = _service()
        mocks["review_queue_repo"].get_by_id.return_value = None
        with pytest.raises(NotFoundError):
            await service.get_review_item(uuid.uuid4())

    async def test_update_review_item_sets_reviewed_at_on_resolve(self) -> None:
        service, mocks = _service()
        item_id = uuid.uuid4()
        existing = object()
        mocks["review_queue_repo"].get_by_id.return_value = existing

        async def _update(item: object, **fields: object) -> object:
            assert item is existing
            assert fields["status"] is ReviewStatus.RESOLVED
            assert "reviewed_at" in fields
            return _StubReviewItem(status=fields["status"])

        mocks["review_queue_repo"].update.side_effect = _update

        result = await service.update_review_item(
            item_id,
            status=ReviewStatus.RESOLVED,
            assigned_to=None,
            resolution="looks fine",
            requested_by=uuid.uuid4(),
        )
        assert result.status is ReviewStatus.RESOLVED

    async def test_update_review_item_without_status_does_not_set_reviewed_at(self) -> None:
        service, mocks = _service()
        mocks["review_queue_repo"].get_by_id.return_value = object()

        captured: dict[str, object] = {}

        async def _update(item: object, **fields: object) -> object:
            captured.update(fields)
            return _StubReviewItem(status=ReviewStatus.PENDING)

        mocks["review_queue_repo"].update.side_effect = _update

        await service.update_review_item(
            uuid.uuid4(),
            status=None,
            assigned_to=uuid.uuid4(),
            resolution=None,
            requested_by=uuid.uuid4(),
        )
        assert "reviewed_at" not in captured
        assert "assigned_to" in captured


class _StubReviewItem:
    def __init__(self, *, status: ReviewStatus) -> None:
        self.status = status
