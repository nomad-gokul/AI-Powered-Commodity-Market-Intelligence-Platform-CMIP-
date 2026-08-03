"""The AgentEngine abstraction.

Business logic (a future pipeline service) depends on this interface only,
never on a concrete backend - SequentialEngine today, a LangGraphEngine
later, is a construction-time choice, not a code change anywhere that
calls .run(). This is the same shape as StorageProvider/LLMProvider:
one ABC, swappable implementations, callers coded against the ABC.
"""

from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from app.ai.agents.base import Agent
from app.ai.engine.types import (
    AgentContext,
    AgentEngineResult,
    ProgressCallback,
    RetryPolicy,
)

DEFAULT_STEP_TIMEOUT_SECONDS = 120.0


@dataclass(frozen=True, slots=True)
class EngineStep:
    """One agent's place in a pipeline, plus its execution policy.

    `condition` supports conditional branching: if it returns False given
    the context accumulated so far, the engine records the step as SKIPPED
    without invoking the agent at all (e.g. "only run OCR agent if the
    document-understanding step decided the page is scanned").

    `continue_on_failure` supports failure recovery: by default an engine
    stops the run at the first step whose retry policy is exhausted, since
    most pipelines are linear dependency chains (step 3 needs step 2's
    output). Setting this True lets a genuinely independent, best-effort
    step (e.g. an optional enrichment) fail without aborting the run.
    """

    agent: Agent
    retry_policy: RetryPolicy = RetryPolicy()
    timeout_seconds: float = DEFAULT_STEP_TIMEOUT_SECONDS
    condition: Callable[[AgentContext], bool] | None = None
    continue_on_failure: bool = False


class AgentEngine(ABC):
    @abstractmethod
    async def run(
        self,
        steps: Sequence[EngineStep],
        context: AgentContext,
        *,
        progress_callback: ProgressCallback | None = None,
    ) -> AgentEngineResult:
        """Execute `steps` against `context` and return the aggregate result.

        Implementations must:
        - honor context.cancellation_token, stopping between steps (or
          within a step, if the agent itself cooperates) and marking
          remaining steps CANCELLED rather than SKIPPED
        - retry a failing step per its RetryPolicy before giving up on it
        - enforce each step's timeout_seconds
        - invoke progress_callback (if given) after every step transition
        - stop the run on the first step that exhausts its retries, unless
          that step has continue_on_failure=True
        """
        ...
