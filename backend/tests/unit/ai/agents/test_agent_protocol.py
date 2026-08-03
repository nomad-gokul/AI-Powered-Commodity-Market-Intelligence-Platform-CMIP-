"""Unit tests for the Agent Protocol: structural typing works without
inheritance, and an object missing `run`/`name` doesn't satisfy it."""

from app.ai.agents.base import Agent
from app.ai.engine.types import AgentContext


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
