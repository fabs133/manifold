"""
Context - Shared state container for workflow runs.

The Context holds all data flowing through the workflow:
- data: Dictionary of facts (inputs, extracted entities, intermediate results)
- artifacts: Files and external references produced by agents
- trace: Complete history of step attempts and spec results
- budgets: Retry and cost limits
"""

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any
import hashlib
import json


@dataclass(frozen=True)
class Artifact:
    """
    An artifact produced during the workflow.

    Artifacts are files or external resources created by agents.
    They are immutable once created.
    """
    path: str
    content_hash: str
    created_at: datetime
    created_by_step: str
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_content(
        cls,
        path: str,
        content: bytes | str,
        created_by_step: str,
        metadata: dict[str, Any] | None = None
    ) -> "Artifact":
        """Create an artifact from content, computing the hash automatically."""
        if isinstance(content, str):
            content = content.encode("utf-8")
        content_hash = hashlib.sha256(content).hexdigest()
        return cls(
            path=path,
            content_hash=content_hash,
            created_at=datetime.now(),
            created_by_step=created_by_step,
            metadata=metadata or {}
        )


@dataclass(frozen=True)
class ToolCall:
    """Record of a tool/function call made by an agent."""
    name: str
    args: dict[str, Any]
    result: Any
    duration_ms: int
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "args": self.args,
            "result": self.result,
            "duration_ms": self.duration_ms,
            "timestamp": self.timestamp.isoformat()
        }


@dataclass(frozen=True)
class SpecResultRef:
    """
    Reference to a spec result in a trace entry.

    This is a lightweight reference; full SpecResult is in the spec module.
    """
    rule_id: str
    passed: bool
    message: str
    suggested_fix: str | None = None
    tags: tuple[str, ...] = ()
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "passed": self.passed,
            "message": self.message,
            "suggested_fix": self.suggested_fix,
            "tags": list(self.tags),
            "data": self.data
        }


@dataclass(frozen=True)
class TraceEntry:
    """
    Record of a single step attempt.

    Every execution of a step creates a TraceEntry, regardless of success.
    This enables full auditability and debugging.
    """
    timestamp: datetime
    step_id: str
    attempt: int
    agent_output: Any
    tool_calls: tuple[ToolCall, ...]
    spec_results: tuple[SpecResultRef, ...]
    routing_decision: str | None = None
    duration_ms: int = 0
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "step_id": self.step_id,
            "attempt": self.attempt,
            "agent_output": str(self.agent_output),
            "tool_calls": [tc.to_dict() for tc in self.tool_calls],
            "spec_results": [sr.to_dict() for sr in self.spec_results],
            "routing_decision": self.routing_decision,
            "duration_ms": self.duration_ms,
            "error": self.error
        }

    @property
    def passed(self) -> bool:
        """True if all specs passed."""
        return all(sr.passed for sr in self.spec_results)

    @property
    def failed_rules(self) -> list[str]:
        """List of rule_ids that failed."""
        return [sr.rule_id for sr in self.spec_results if not sr.passed]


@dataclass(frozen=True)
class Budgets:
    """
    Resource limits for the workflow.

    Budgets prevent runaway execution and control costs.
    """
    max_total_attempts: int = 50
    max_attempts_per_step: int = 3
    max_cost_dollars: float = 10.0
    current_attempts: dict[str, int] = field(default_factory=dict)
    current_cost: float = 0.0

    def get_step_attempts(self, step_id: str) -> int:
        """Get current attempt count for a step."""
        return self.current_attempts.get(step_id, 0)

    def get_total_attempts(self) -> int:
        """Get total attempts across all steps."""
        return sum(self.current_attempts.values())

    def is_step_budget_exceeded(self, step_id: str) -> bool:
        """Check if step has exceeded its retry budget."""
        return self.get_step_attempts(step_id) >= self.max_attempts_per_step

    def is_total_budget_exceeded(self) -> bool:
        """Check if total attempts exceeded."""
        return self.get_total_attempts() >= self.max_total_attempts

    def is_cost_exceeded(self) -> bool:
        """Check if cost limit exceeded."""
        return self.current_cost >= self.max_cost_dollars

    def with_incremented_attempt(self, step_id: str) -> "Budgets":
        """Return new Budgets with incremented attempt for step."""
        new_attempts = dict(self.current_attempts)
        new_attempts[step_id] = new_attempts.get(step_id, 0) + 1
        return replace(self, current_attempts=new_attempts)

    def with_added_cost(self, cost: float) -> "Budgets":
        """Return new Budgets with added cost."""
        return replace(self, current_cost=self.current_cost + cost)


@dataclass(frozen=True)
class Context:
    """
    Shared state container for workflow run.

    Context is immutable - updates return new Context instances.
    This ensures predictable state and enables easy debugging.

    Fields:
        run_id: Unique identifier for this workflow run
        data: Dictionary of facts (inputs, intermediate results)
        artifacts: Files and external references
        trace: Complete execution history
        budgets: Resource limits
        history: Optional summaries for LLM context
        metadata: Additional run metadata
    """
    run_id: str
    data: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, Artifact] = field(default_factory=dict)
    trace: tuple[TraceEntry, ...] = ()
    budgets: Budgets = field(default_factory=Budgets)
    history: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def get_data(self, key: str, default: Any = None) -> Any:
        """Get a value from data dict."""
        return self.data.get(key, default)

    def has_data(self, key: str) -> bool:
        """Check if key exists in data."""
        return key in self.data

    def get_artifact(self, path: str) -> Artifact | None:
        """Get an artifact by path."""
        return self.artifacts.get(path)

    def has_artifact(self, path: str) -> bool:
        """Check if artifact exists."""
        return path in self.artifacts

    def get_last_trace_for_step(self, step_id: str) -> TraceEntry | None:
        """Get the most recent trace entry for a step."""
        for entry in reversed(self.trace):
            if entry.step_id == step_id:
                return entry
        return None

    def get_traces_for_step(self, step_id: str) -> list[TraceEntry]:
        """Get all trace entries for a step."""
        return [e for e in self.trace if e.step_id == step_id]

    def to_dict(self) -> dict:
        """Serialize context to dictionary."""
        return {
            "run_id": self.run_id,
            "data": self.data,
            "artifacts": {k: {"path": v.path, "hash": v.content_hash} for k, v in self.artifacts.items()},
            "trace_count": len(self.trace),
            "budgets": {
                "total_attempts": self.budgets.get_total_attempts(),
                "max_total": self.budgets.max_total_attempts,
                "cost": self.budgets.current_cost,
                "max_cost": self.budgets.max_cost_dollars
            },
            "metadata": self.metadata
        }


class ContextUpdater:
    """
    Controlled mutations to Context.

    All updates return new Context instances (immutable pattern).
    This class provides the only sanctioned ways to modify context.
    """

    @staticmethod
    def patch_data(ctx: Context, key: str, value: Any) -> Context:
        """Add or update a data field."""
        new_data = {**ctx.data, key: value}
        return replace(ctx, data=new_data)

    @staticmethod
    def patch_data_many(ctx: Context, updates: dict[str, Any]) -> Context:
        """Update multiple data fields at once."""
        new_data = {**ctx.data, **updates}
        return replace(ctx, data=new_data)

    @staticmethod
    def remove_data(ctx: Context, key: str) -> Context:
        """Remove a data field."""
        new_data = {k: v for k, v in ctx.data.items() if k != key}
        return replace(ctx, data=new_data)

    @staticmethod
    def append_artifact(ctx: Context, artifact: Artifact) -> Context:
        """Add an artifact."""
        new_artifacts = {**ctx.artifacts, artifact.path: artifact}
        return replace(ctx, artifacts=new_artifacts)

    @staticmethod
    def append_trace(ctx: Context, entry: TraceEntry) -> Context:
        """Add a trace entry."""
        return replace(ctx, trace=(*ctx.trace, entry))

    @staticmethod
    def increment_attempt(ctx: Context, step_id: str) -> Context:
        """Increment attempt counter for a step."""
        new_budgets = ctx.budgets.with_incremented_attempt(step_id)
        return replace(ctx, budgets=new_budgets)

    @staticmethod
    def add_cost(ctx: Context, cost: float) -> Context:
        """Add cost to the budget."""
        new_budgets = ctx.budgets.with_added_cost(cost)
        return replace(ctx, budgets=new_budgets)

    @staticmethod
    def append_history(ctx: Context, summary: str) -> Context:
        """Add a history summary."""
        return replace(ctx, history=(*ctx.history, summary))

    @staticmethod
    def set_metadata(ctx: Context, key: str, value: Any) -> Context:
        """Set a metadata field."""
        new_metadata = {**ctx.metadata, key: value}
        return replace(ctx, metadata=new_metadata)


def create_context(
    run_id: str,
    initial_data: dict[str, Any] | None = None,
    budgets: Budgets | None = None,
    metadata: dict[str, Any] | None = None
) -> Context:
    """
    Factory function to create a new Context.

    Args:
        run_id: Unique identifier for this run
        initial_data: Initial data to populate
        budgets: Custom budget limits (uses defaults if None)
        metadata: Additional metadata

    Returns:
        New Context instance
    """
    return Context(
        run_id=run_id,
        data=initial_data or {},
        budgets=budgets or Budgets(),
        metadata=metadata or {"created_at": datetime.now().isoformat()}
    )
