"""SequentialEngine: the default, real AgentEngine backend.

Runs steps strictly in order, threading each step's output onto
`context.state[step.agent.name]` (the blackboard) before the next step
runs, so later steps can read earlier steps' output. This is the
appropriate default for a document pipeline where each stage genuinely
depends on the previous one's result; a future LangGraphEngine can offer
graph/DAG execution for pipelines that don't fit a strict chain, behind the
same AgentEngine interface.
"""

import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime

from app.ai.engine.base import AgentEngine, EngineStep
from app.ai.engine.types import (
    AgentContext,
    AgentEngineResult,
    AgentStepResult,
    ProgressCallback,
    StepProgress,
    StepStatus,
)


class SequentialEngine(AgentEngine):
    async def run(
        self,
        steps: Sequence[EngineStep],
        context: AgentContext,
        *,
        progress_callback: ProgressCallback | None = None,
    ) -> AgentEngineResult:
        results: list[AgentStepResult] = []
        total = len(steps)
        cancelled = False
        hard_failure = False

        for index, step in enumerate(steps):
            if context.cancellation_token.is_cancelled:
                cancelled = True
                break

            if step.condition is not None and not step.condition(context):
                result = AgentStepResult(agent_name=step.agent.name, status=StepStatus.SKIPPED)
                result.completed_at = result.started_at
                results.append(result)
                await self._emit(
                    progress_callback, result.agent_name, result.status, index, total
                )
                continue

            step_result = await self._run_step(step, context, progress_callback, index, total)
            results.append(step_result)
            context.state[step.agent.name] = step_result.output

            if context.cancellation_token.is_cancelled:
                # Cancellation may have fired while this step was mid-retry;
                # give it priority over failure bookkeeping so every step
                # after this one is reported CANCELLED, not "skipped due to
                # upstream failure".
                cancelled = True
                break

            if step_result.status in (StepStatus.FAILED, StepStatus.TIMED_OUT):
                if not step.continue_on_failure:
                    hard_failure = True
                    break

        if cancelled or hard_failure:
            if cancelled:
                reason = "run cancelled"
            else:
                reason = f"upstream step {results[-1].agent_name!r} failed"
            skip_status = StepStatus.CANCELLED if cancelled else StepStatus.SKIPPED
            for index, step in enumerate(steps[len(results) :], start=len(results)):
                skipped = AgentStepResult(
                    agent_name=step.agent.name, status=skip_status, error=reason
                )
                skipped.completed_at = skipped.started_at
                results.append(skipped)
                await self._emit(
                    progress_callback, skipped.agent_name, skip_status, index, total, reason
                )

        return AgentEngineResult(
            steps=results, succeeded=not (cancelled or hard_failure), cancelled=cancelled
        )

    async def _run_step(
        self,
        step: EngineStep,
        context: AgentContext,
        progress_callback: ProgressCallback | None,
        index: int,
        total: int,
    ) -> AgentStepResult:
        started_at = datetime.now(UTC)
        await self._emit(progress_callback, step.agent.name, StepStatus.RUNNING, index, total)

        attempt = 0
        last_error = "unknown error"
        status_on_exhaustion = StepStatus.FAILED
        while True:
            attempt += 1
            try:
                output = await asyncio.wait_for(
                    step.agent.run(context), timeout=step.timeout_seconds
                )
            except TimeoutError:
                last_error = f"timed out after {step.timeout_seconds}s"
                status_on_exhaustion = StepStatus.TIMED_OUT
            except Exception as exc:  # noqa: BLE001 - deliberately broad: any agent failure is retryable data
                last_error = f"{type(exc).__name__}: {exc}"
                status_on_exhaustion = StepStatus.FAILED
            else:
                result = AgentStepResult(
                    agent_name=step.agent.name,
                    status=StepStatus.SUCCEEDED,
                    output=output,
                    retries_used=attempt - 1,
                    started_at=started_at,
                    completed_at=datetime.now(UTC),
                )
                await self._emit(
                    progress_callback, step.agent.name, StepStatus.SUCCEEDED, index, total
                )
                return result

            retries_exhausted = attempt >= step.retry_policy.max_attempts
            if retries_exhausted or context.cancellation_token.is_cancelled:
                result = AgentStepResult(
                    agent_name=step.agent.name,
                    status=status_on_exhaustion,
                    error=last_error,
                    retries_used=attempt - 1,
                    started_at=started_at,
                    completed_at=datetime.now(UTC),
                )
                await self._emit(
                    progress_callback,
                    step.agent.name,
                    status_on_exhaustion,
                    index,
                    total,
                    last_error,
                )
                return result

            await asyncio.sleep(step.retry_policy.delay_for_attempt(attempt))

    @staticmethod
    async def _emit(
        callback: ProgressCallback | None,
        agent_name: str,
        status: StepStatus,
        index: int,
        total: int,
        message: str | None = None,
    ) -> None:
        if callback is None:
            return
        await callback(
            StepProgress(
                agent_name=agent_name,
                status=status,
                sequence_index=index,
                total_steps=total,
                message=message,
            )
        )
