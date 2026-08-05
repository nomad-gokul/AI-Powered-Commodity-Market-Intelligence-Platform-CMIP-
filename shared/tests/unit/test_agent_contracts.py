"""Unit tests for shared.agent_contracts: the Agent Protocol satisfies
structural typing without inheritance, and the primitives it's built from
(CancellationToken, RetryPolicy, AgentStepResult) behave correctly
exercised directly, not only indirectly through SequentialEngine."""

import asyncio

from shared.agent_contracts import (
    Agent,
    AgentContext,
    AgentStepResult,
    CancellationToken,
    RetryPolicy,
    StepStatus,
)


class ConformingAgent:
    @property
    def name(self) -> str:
        return "conforming"

    async def run(self, context: AgentContext) -> str:
        return "ok"


class MissingRunMethod:
    @property
    def name(self) -> str:
        return "incomplete"


class TestAgentProtocol:
    def test_structurally_conforming_class_satisfies_protocol_without_inheritance(self) -> None:
        assert isinstance(ConformingAgent(), Agent)

    def test_class_missing_run_does_not_satisfy_protocol(self) -> None:
        assert isinstance(MissingRunMethod(), Agent) is False


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
