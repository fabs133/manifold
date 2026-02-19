"""
Agent - Workers that transform context into output.

Agents are the "organs" of the workflow:
- Accept context (or derived input)
- Produce structured output
- Record tool calls
- Do NOT decide global control flow

The Orchestrator decides what happens next based on specs and routing.
Agents just do their job and report results.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from manifold.core.context import Context, Artifact

# Re-export ToolCall from context module (single source of truth)
from manifold.core.context import ToolCall


@dataclass
class AgentOutput:
    """
    Standard output from any agent.

    All agents return AgentOutput for consistency:
    - output: The primary result (can be any type)
    - delta: Context data updates to apply
    - artifacts: New files/resources created
    - tool_calls: Record of tools used
    - raw: Raw model response (for debugging)
    - proposed_next: Hint for routing (not authoritative)
    """

    output: Any
    delta: dict[str, Any] | None = None
    artifacts: list["Artifact"] | None = None
    tool_calls: list[ToolCall] | None = None
    raw: str | None = None
    proposed_next: str | None = None  # Agent's suggestion (hint only)
    cost: float = 0.0  # Cost in dollars

    def get_tool_calls(self) -> list[ToolCall]:
        """Get tool calls, defaulting to empty list."""
        return self.tool_calls or []

    def get_artifacts(self) -> list["Artifact"]:
        """Get artifacts, defaulting to empty list."""
        return self.artifacts or []

    def get_delta(self) -> dict[str, Any]:
        """Get delta, defaulting to empty dict."""
        return self.delta or {}

    def total_duration_ms(self) -> int:
        """Calculate total duration of all tool calls."""
        return sum(tc.duration_ms for tc in self.get_tool_calls())


class Agent(ABC):
    """
    Base class for all agents.

    An Agent transforms context into output:
    - Receives context and optional input data
    - Performs its specialized task
    - Returns structured AgentOutput
    - Does NOT decide workflow routing

    Subclasses must implement:
    - agent_id: Unique identifier
    - execute(): The agent's core logic
    """

    @property
    @abstractmethod
    def agent_id(self) -> str:
        """Unique identifier for this agent type."""
        pass

    @property
    def description(self) -> str:
        """Human-readable description of what this agent does."""
        return f"Agent: {self.agent_id}"

    @abstractmethod
    async def execute(
        self, context: "Context", input_data: dict[str, Any] | None = None
    ) -> AgentOutput:
        """
        Execute the agent's task.

        Args:
            context: Current workflow context
            input_data: Optional step-specific input

        Returns:
            AgentOutput with results

        Contract:
            - Must return AgentOutput
            - Must record all tool calls
            - Must NOT mutate context directly
            - Should NOT decide routing (use proposed_next as hint only)
        """
        pass

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(agent_id={self.agent_id!r})"


class AgentAdapter:
    """
    Adapter for wrapping external agent implementations.

    Use this to integrate agents from other frameworks
    (e.g., OpenAI Agents SDK, LangChain, etc.)
    """

    def __init__(self, agent_id: str, execute_fn, description: str = ""):
        self._agent_id = agent_id
        self._execute_fn = execute_fn
        self._description = description or f"Adapted agent: {agent_id}"

    @property
    def agent_id(self) -> str:
        return self._agent_id

    @property
    def description(self) -> str:
        return self._description

    async def execute(
        self, context: "Context", input_data: dict[str, Any] | None = None
    ) -> AgentOutput:
        """Execute the wrapped agent function."""
        result = await self._execute_fn(context, input_data)

        # Normalize result to AgentOutput
        if isinstance(result, AgentOutput):
            return result
        elif isinstance(result, dict):
            return AgentOutput(
                output=result.get("output"),
                delta=result.get("delta"),
                artifacts=result.get("artifacts"),
                tool_calls=result.get("tool_calls"),
                raw=result.get("raw"),
            )
        else:
            # Treat as raw output
            return AgentOutput(output=result)


class AgentRegistry:
    """
    Registry for agent instances.

    Agents are registered by their agent_id for lookup during execution.
    """

    def __init__(self):
        self._agents: dict[str, Agent | AgentAdapter] = {}

    def register(self, agent: Agent | AgentAdapter) -> None:
        """Register an agent."""
        if agent.agent_id in self._agents:
            raise ValueError(f"Agent with id '{agent.agent_id}' already registered")
        self._agents[agent.agent_id] = agent

    def register_many(self, agents: list[Agent | AgentAdapter]) -> None:
        """Register multiple agents."""
        for agent in agents:
            self.register(agent)

    def get(self, agent_id: str) -> Agent | AgentAdapter | None:
        """Get an agent by id."""
        return self._agents.get(agent_id)

    def get_required(self, agent_id: str) -> Agent | AgentAdapter:
        """Get an agent, raising if not found."""
        agent = self.get(agent_id)
        if agent is None:
            raise KeyError(f"No agent registered with id '{agent_id}'")
        return agent

    def list_agents(self) -> list[str]:
        """List all registered agent ids."""
        return list(self._agents.keys())


# ─── SIMPLE AGENT IMPLEMENTATIONS ───────────────────────────────────────────


class PassthroughAgent(Agent):
    """
    Agent that passes input directly to output.

    Useful for testing and as a template.
    """

    agent_id = "passthrough"

    async def execute(
        self, context: "Context", input_data: dict[str, Any] | None = None
    ) -> AgentOutput:
        return AgentOutput(output=input_data, delta=input_data)


class FailingAgent(Agent):
    """
    Agent that always fails.

    Useful for testing error handling.
    """

    def __init__(self, error_message: str = "Intentional failure"):
        self._error_message = error_message

    @property
    def agent_id(self) -> str:
        return "failing"

    async def execute(
        self, context: "Context", input_data: dict[str, Any] | None = None
    ) -> AgentOutput:
        raise RuntimeError(self._error_message)


class FunctionAgent(Agent):
    """
    Agent that wraps a simple function.

    Useful for quick agent creation without subclassing.
    """

    def __init__(self, agent_id: str, fn, description: str = ""):
        self._agent_id = agent_id
        self._fn = fn
        self._description = description

    @property
    def agent_id(self) -> str:
        return self._agent_id

    @property
    def description(self) -> str:
        return self._description or f"Function agent: {self._agent_id}"

    async def execute(
        self, context: "Context", input_data: dict[str, Any] | None = None
    ) -> AgentOutput:
        import inspect

        # Call function (handle both sync and async)
        if inspect.iscoroutinefunction(self._fn):
            result = await self._fn(context, input_data)
        else:
            result = self._fn(context, input_data)

        # Normalize to AgentOutput
        if isinstance(result, AgentOutput):
            return result
        elif isinstance(result, dict):
            return AgentOutput(output=result.get("output", result), delta=result.get("delta"))
        else:
            return AgentOutput(output=result)
