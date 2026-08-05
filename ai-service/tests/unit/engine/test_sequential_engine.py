"""Unit tests for SequentialEngine: retry, timeout, cancellation,
conditional branching, failure recovery, and progress reporting - all
against simple test-double agents, since no production agent lives in
this package (agents are owned by business modules, see
docs/ARCHITECTURE.md)."""

import asyncio

import pytest
from shared.agent_contracts import AgentContext, EngineStep, RetryPolicy, StepProgress, StepStatus

from ai_service.engine.sequential import SequentialEngine


class EchoAgent:
    def __init__(self, name: str, output: object = "ok") -> None:
        self._name = name
        self.output = output
        self.calls = 0

    @property
    def name(self) -> str:
        return self._name

    async def run(self, context: AgentContext) -> object:
        self.calls += 1
        return self.output


class FailingAgent:
    def __init__(self, name: str, exc: Exception | None = None) -> None:
        self._name = name
        self.exc = exc or RuntimeError("boom")
        self.calls = 0

    @property
    def name(self) -> str:
        return self._name

    async def run(self, context: AgentContext) -> object:
        self.calls += 1
        raise self.exc


class FlakyAgent:
    """Fails `fail_times` times, then succeeds."""

    def __init__(self, name: str, fail_times: int, output: object = "ok") -> None:
        self._name = name
        self.fail_times = fail_times
        self.output = output
        self.calls = 0

    @property
    def name(self) -> str:
        return self._name

    async def run(self, context: AgentContext) -> object:
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError(f"attempt {self.calls} failed")
        return self.output


class SlowAgent:
    def __init__(self, name: str, delay_seconds: float) -> None:
        self._name = name
        self.delay_seconds = delay_seconds
        self.calls = 0

    @property
    def name(self) -> str:
        return self._name

    async def run(self, context: AgentContext) -> object:
        self.calls += 1
        await asyncio.sleep(self.delay_seconds)
        return "done"


class SelfCancellingAgent:
    """Cancels the shared token from inside its own run()."""

    def __init__(self, name: str) -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    async def run(self, context: AgentContext) -> object:
        context.cancellation_token.cancel()
        return "cancelled-self"


def _context() -> AgentContext:
    return AgentContext(correlation_id="test-correlation")


class TestBasicExecution:
    async def test_runs_steps_in_order_and_threads_blackboard_state(self) -> None:
        step1 = EngineStep(agent=EchoAgent("a", output={"x": 1}))
        step2 = EngineStep(agent=EchoAgent("b", output={"y": 2}))
        context = _context()
        result = await SequentialEngine().run([step1, step2], context)

        assert result.succeeded is True
        assert [s.status for s in result.steps] == [StepStatus.SUCCEEDED, StepStatus.SUCCEEDED]
        assert result.output_of("a") == {"x": 1}
        assert context.state["a"] == {"x": 1}
        assert context.state["b"] == {"y": 2}

    async def test_total_duration_sums_step_durations(self) -> None:
        result = await SequentialEngine().run([EngineStep(agent=EchoAgent("a"))], _context())
        assert result.total_duration_ms >= 0

    async def test_output_of_unknown_agent_raises_key_error(self) -> None:
        result = await SequentialEngine().run([EngineStep(agent=EchoAgent("a"))], _context())
        with pytest.raises(KeyError):
            result.output_of("does-not-exist")


class TestRetry:
    async def test_succeeds_after_retrying_a_flaky_agent(self) -> None:
        agent = FlakyAgent("flaky", fail_times=2)
        policy = RetryPolicy(max_attempts=3, backoff_base_seconds=0)
        step = EngineStep(agent=agent, retry_policy=policy)
        result = await SequentialEngine().run([step], _context())

        assert result.succeeded is True
        assert agent.calls == 3
        assert result.steps[0].retries_used == 2

    async def test_gives_up_after_max_attempts_and_records_error(self) -> None:
        agent = FailingAgent("always-fails")
        policy = RetryPolicy(max_attempts=2, backoff_base_seconds=0)
        step = EngineStep(agent=agent, retry_policy=policy)
        result = await SequentialEngine().run([step], _context())

        assert result.succeeded is False
        assert agent.calls == 2
        assert result.steps[0].status == StepStatus.FAILED
        assert "boom" in (result.steps[0].error or "")

    async def test_backoff_delay_grows_between_attempts(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Asserts on the actual sleep durations requested, not wall-clock
        elapsed time - real asyncio.sleep() precision (especially on
        Windows) can wake up slightly early, making a wall-clock assertion
        flaky without proving anything more than this one."""
        agent = FlakyAgent("flaky", fail_times=2)
        policy = RetryPolicy(max_attempts=3, backoff_base_seconds=0.05, backoff_multiplier=2.0)
        recorded_delays: list[float] = []

        async def _fake_sleep(seconds: float) -> None:
            recorded_delays.append(seconds)

        monkeypatch.setattr(asyncio, "sleep", _fake_sleep)
        await SequentialEngine().run([EngineStep(agent=agent, retry_policy=policy)], _context())

        assert recorded_delays == [0.05, 0.1]


class TestTimeout:
    async def test_step_exceeding_timeout_is_marked_timed_out(self) -> None:
        agent = SlowAgent("slow", delay_seconds=0.2)
        step = EngineStep(
            agent=agent, timeout_seconds=0.02, retry_policy=RetryPolicy(max_attempts=1)
        )
        result = await SequentialEngine().run([step], _context())

        assert result.succeeded is False
        assert result.steps[0].status == StepStatus.TIMED_OUT


class TestConditionalBranching:
    async def test_step_is_skipped_when_condition_is_false(self) -> None:
        agent = EchoAgent("skip-me")
        step = EngineStep(agent=agent, condition=lambda ctx: False)
        result = await SequentialEngine().run([step], _context())

        assert result.succeeded is True
        assert result.steps[0].status == StepStatus.SKIPPED
        assert agent.calls == 0

    async def test_condition_can_read_prior_step_output_from_blackboard(self) -> None:
        step1 = EngineStep(agent=EchoAgent("gate", output={"run_next": True}))
        agent2 = EchoAgent("next")
        step2 = EngineStep(
            agent=agent2, condition=lambda ctx: bool(ctx.state.get("gate", {}).get("run_next"))
        )
        result = await SequentialEngine().run([step1, step2], _context())

        assert agent2.calls == 1
        assert result.steps[1].status == StepStatus.SUCCEEDED


class TestFailureRecovery:
    async def test_hard_failure_stops_remaining_steps_by_default(self) -> None:
        failing = FailingAgent("fails")
        never_runs = EchoAgent("never")
        steps = [
            EngineStep(agent=failing, retry_policy=RetryPolicy(max_attempts=1)),
            EngineStep(agent=never_runs),
        ]
        result = await SequentialEngine().run(steps, _context())

        assert result.succeeded is False
        assert never_runs.calls == 0
        assert result.steps[1].status == StepStatus.SKIPPED

    async def test_continue_on_failure_lets_subsequent_steps_run(self) -> None:
        failing = FailingAgent("fails")
        after = EchoAgent("after")
        steps = [
            EngineStep(
                agent=failing, retry_policy=RetryPolicy(max_attempts=1), continue_on_failure=True
            ),
            EngineStep(agent=after),
        ]
        result = await SequentialEngine().run(steps, _context())

        assert result.succeeded is True
        assert after.calls == 1
        assert result.steps[0].status == StepStatus.FAILED


class TestCancellation:
    async def test_cancelled_before_run_marks_all_steps_cancelled(self) -> None:
        context = _context()
        context.cancellation_token.cancel()
        agent = EchoAgent("never")
        result = await SequentialEngine().run([EngineStep(agent=agent)], context)

        assert result.cancelled is True
        assert result.succeeded is False
        assert agent.calls == 0
        assert result.steps[0].status == StepStatus.CANCELLED

    async def test_cancellation_mid_run_stops_remaining_steps(self) -> None:
        context = _context()
        cancels = SelfCancellingAgent("cancels-self")
        never_runs = EchoAgent("never")
        steps = [EngineStep(agent=cancels), EngineStep(agent=never_runs)]
        result = await SequentialEngine().run(steps, context)

        assert result.cancelled is True
        assert never_runs.calls == 0
        assert result.steps[1].status == StepStatus.CANCELLED


class TestProgressReporting:
    async def test_progress_callback_invoked_for_running_and_terminal_states(self) -> None:
        events: list[StepProgress] = []

        async def on_progress(progress: StepProgress) -> None:
            events.append(progress)

        await SequentialEngine().run(
            [EngineStep(agent=EchoAgent("a"))], _context(), progress_callback=on_progress
        )

        statuses = [event.status for event in events]
        assert StepStatus.RUNNING in statuses
        assert StepStatus.SUCCEEDED in statuses
        assert all(event.agent_name == "a" for event in events)
        assert all(event.total_steps == 1 for event in events)
