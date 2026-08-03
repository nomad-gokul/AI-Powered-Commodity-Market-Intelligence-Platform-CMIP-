"""Unit tests for engine/types.py primitives, exercised directly rather
than only indirectly through SequentialEngine."""

import asyncio

from app.ai.engine.types import AgentStepResult, CancellationToken, RetryPolicy, StepStatus


class TestCancellationToken:
    async def test_wait_returns_immediately_once_cancelled(self) -> None:
        token = CancellationToken()
        token.cancel()
        await asyncio.wait_for(token.wait(), timeout=0.1)

    async def test_wait_blocks_until_cancel_is_called(self) -> None:
        token = CancellationToken()
        waiter = asyncio.ensure_future(token.wait())
        await asyncio.sleep(0.01)
        assert not waiter.done()
        token.cancel()
        await asyncio.wait_for(waiter, timeout=0.1)

    def test_is_cancelled_false_before_cancel(self) -> None:
        assert CancellationToken().is_cancelled is False


class TestRetryPolicy:
    def test_delay_grows_exponentially_with_multiplier(self) -> None:
        policy = RetryPolicy(max_attempts=5, backoff_base_seconds=2.0, backoff_multiplier=3.0)
        assert policy.delay_for_attempt(1) == 2.0
        assert policy.delay_for_attempt(2) == 6.0
        assert policy.delay_for_attempt(3) == 18.0


class TestAgentStepResult:
    def test_duration_ms_is_none_when_not_completed(self) -> None:
        result = AgentStepResult(agent_name="a", status=StepStatus.RUNNING)
        assert result.duration_ms is None
