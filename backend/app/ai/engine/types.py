"""Shared types for the AgentEngine abstraction.

Nothing in this module knows about a concrete engine backend (Sequential,
LangGraph-later) or about LLM providers - it is the vocabulary every backend
and every agent is written against.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class CancellationToken:
    """Cooperative cancellation signal shared across an engine run.

    Wraps an asyncio.Event rather than relying on task.cancel() so a step
    can check `is_cancelled` at a safe boundary (between steps, or inside a
    long-running agent's own loop) instead of having a CancelledError thrown
    at an arbitrary await point.
    """

    def __init__(self) -> None:
        self._event = asyncio.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    async def wait(self) -> None:
        await self._event.wait()


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Per-step retry configuration. max_attempts=1 means "no retry"."""

    max_attempts: int = 1
    backoff_base_seconds: float = 1.0
    backoff_multiplier: float = 2.0

    def delay_for_attempt(self, attempt: int) -> float:
        """attempt is 1-indexed: the delay BEFORE the given retry attempt."""
        return self.backoff_base_seconds * (self.backoff_multiplier ** (attempt - 1))


@dataclass(slots=True)
class AgentContext:
    """Mutable state threaded through an engine run.

    `state` is the blackboard agents read prior-step output from and write
    their own output to, keyed by agent name - this is deliberately a plain
    dict rather than a typed structure, since the concrete keys are defined
    by whatever agents a later phase registers, not by the engine itself.
    """

    correlation_id: str
    cancellation_token: CancellationToken = field(default_factory=CancellationToken)
    state: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


class StepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


@dataclass(slots=True)
class StepProgress:
    """Emitted to a ProgressCallback after every step transition."""

    agent_name: str
    status: StepStatus
    sequence_index: int
    total_steps: int
    message: str | None = None


ProgressCallback = Callable[[StepProgress], Awaitable[None]]


@dataclass(slots=True)
class AgentStepResult:
    """Outcome of running a single agent within an engine run."""

    agent_name: str
    status: StepStatus
    output: Any = None
    error: str | None = None
    retries_used: int = 0
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None

    @property
    def duration_ms(self) -> float | None:
        if self.completed_at is None:
            return None
        return (self.completed_at - self.started_at).total_seconds() * 1000


@dataclass(slots=True)
class AgentEngineResult:
    """Outcome of a full engine run across every step."""

    steps: list[AgentStepResult]
    succeeded: bool
    cancelled: bool = False

    @property
    def total_duration_ms(self) -> float:
        return sum(step.duration_ms or 0.0 for step in self.steps)

    def output_of(self, agent_name: str) -> Any:
        """Return the output of the named step, or raise KeyError."""
        for step in self.steps:
            if step.agent_name == agent_name:
                return step.output
        raise KeyError(f"No step result for agent {agent_name!r}")
