"""The Agent contract.

An Agent knows how to do one job given a context. It knows nothing about
*how* it gets invoked: not the engine backend, not retries, not timeouts,
not execution order relative to other agents, not whether it's step 1 of 1
or step 4 of 9. All of that is the engine's job (see app.ai.engine). This
is what lets AgentEngine implementations be swapped (Sequential today,
LangGraph later) without touching a single agent.

Agent is a Protocol, not a base class: nothing about implementing an agent
requires inheriting from app.ai code, keeping agents (a later phase's
concern) decoupled from this package's internals.
"""

from typing import Any, Protocol, runtime_checkable

from app.ai.engine.types import AgentContext


@runtime_checkable
class Agent(Protocol):
    """A unit of work the engine can execute.

    `name` must be stable and unique within a single engine run - it's the
    key other agents and the caller use to look up this step's output from
    AgentEngineResult.output_of() / AgentContext.state.
    """

    @property
    def name(self) -> str: ...

    async def run(self, context: AgentContext) -> Any:
        """Do the agent's work and return its output.

        Implementations should raise on failure rather than returning a
        sentinel - the engine is responsible for catching exceptions,
        applying retry policy, and recording AgentStepResult.error.
        """
        ...
