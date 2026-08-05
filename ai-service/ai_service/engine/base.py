"""The AgentEngine abstraction.

Business logic (app.modules.extraction/.trust/.graph's pipeline services)
depends on this interface only, never on a concrete backend -
SequentialEngine today, a LangGraphEngine later, is a construction-time
choice, not a code change anywhere that calls .run(). This is the same
shape as StorageProvider/LLMProvider: one ABC, swappable implementations,
callers coded against the ABC.

EngineStep, AgentContext, AgentEngineResult, and ProgressCallback live in
shared.agent_contracts, not here (Pre-Phase 5 AI Service Extraction) -
they're the declarative vocabulary business-module pipeline code builds
directly, so they're a shared contract; this ABC is ai-service's one
concrete-swappable piece of behavior above them.
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence

from shared.agent_contracts import AgentContext, AgentEngineResult, EngineStep, ProgressCallback


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
