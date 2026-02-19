"""Tests for the Orchestrator — the main workflow execution loop."""

import pytest
from typing import Any

from manifold.core.orchestrator import (
    Orchestrator,
    OrchestratorBuilder,
    WorkflowResult,
    StepExecutionResult,
    run_workflow,
)
from manifold.core.context import Context, create_context, Budgets
from manifold.core.agent import Agent, AgentOutput, AgentRegistry, PassthroughAgent, FailingAgent
from manifold.core.spec import Spec, SpecResult, SpecEngine
from manifold.core.manifest import Manifest, Step, Edge, GlobalConfig, ManifestLoader
from manifold.core.router import COMPLETE, FAIL


# ── Test Agents ──────────────────────────────────────────────────────────────

class EchoAgent(Agent):
    """Agent that echoes input data as output and writes to delta."""

    def __init__(self, agent_id: str = "echo"):
        self._id = agent_id

    @property
    def agent_id(self) -> str:
        return self._id

    async def execute(self, context: Context, input_data: dict[str, Any] | None = None) -> AgentOutput:
        value = context.get_data("input", "default")
        return AgentOutput(
            output={"echoed": value},
            delta={"result": value},
            cost=0.01,
        )


class CountingAgent(Agent):
    """Agent that counts how many times it has been called."""

    def __init__(self, agent_id: str = "counter"):
        self._id = agent_id
        self.call_count = 0

    @property
    def agent_id(self) -> str:
        return self._id

    async def execute(self, context: Context, input_data: dict[str, Any] | None = None) -> AgentOutput:
        self.call_count += 1
        return AgentOutput(
            output={"count": self.call_count},
            delta={"call_count": self.call_count},
            cost=0.001,
        )


# ── Test Specs ───────────────────────────────────────────────────────────────

class AlwaysPassSpec(Spec):
    @property
    def rule_id(self) -> str:
        return "always_pass"

    @property
    def tags(self) -> tuple[str, ...]:
        return ("postcondition",)

    def evaluate(self, context, candidate=None) -> SpecResult:
        return SpecResult.ok(self.rule_id, tags=self.tags)


class AlwaysFailSpec(Spec):
    @property
    def rule_id(self) -> str:
        return "always_fail"

    @property
    def tags(self) -> tuple[str, ...]:
        return ("postcondition",)

    def evaluate(self, context, candidate=None) -> SpecResult:
        return SpecResult.fail(
            self.rule_id,
            "Always fails",
            suggested_fix="Nothing can fix this",
            tags=self.tags,
        )


class CandidateHasKeySpec(Spec):
    """Passes if candidate dict has a specific key."""

    def __init__(self, key: str):
        self._key = key

    @property
    def rule_id(self) -> str:
        return f"has_key:{self._key}"

    @property
    def tags(self) -> tuple[str, ...]:
        return ("postcondition",)

    def evaluate(self, context, candidate=None) -> SpecResult:
        if isinstance(candidate, dict) and self._key in candidate:
            return SpecResult.ok(self.rule_id, tags=self.tags)
        return SpecResult.fail(
            self.rule_id,
            f"Missing key: {self._key}",
            suggested_fix=f"Agent must return dict with '{self._key}'",
            tags=self.tags,
        )


# ── Manifest Helpers ─────────────────────────────────────────────────────────

SINGLE_STEP_MANIFEST = {
    "manifest_version": "1.0",
    "spec_version": "1.0",
    "globals": {
        "start_step": "process",
        "budgets": {"max_total_attempts": 10, "max_attempts_per_step": 3, "max_cost_dollars": 1.0},
    },
    "steps": {
        "process": {"agent_id": "echo", "post_specs": ["always_pass"]},
    },
    "edges": [
        {"from_step": "process", "to_step": "__complete__", "when": "post_ok", "priority": 10},
        {"from_step": "process", "to_step": "__fail__", "when": "true", "priority": 0},
    ],
}

TWO_STEP_MANIFEST = {
    "manifest_version": "1.0",
    "spec_version": "1.0",
    "globals": {
        "start_step": "step1",
        "budgets": {"max_total_attempts": 10, "max_attempts_per_step": 3, "max_cost_dollars": 1.0},
    },
    "steps": {
        "step1": {"agent_id": "echo", "post_specs": ["always_pass"]},
        "step2": {"agent_id": "echo", "post_specs": ["always_pass"]},
    },
    "edges": [
        {"from_step": "step1", "to_step": "step2", "when": "post_ok", "priority": 10},
        {"from_step": "step1", "to_step": "__fail__", "when": "true", "priority": 0},
        {"from_step": "step2", "to_step": "__complete__", "when": "post_ok", "priority": 10},
        {"from_step": "step2", "to_step": "__fail__", "when": "true", "priority": 0},
    ],
}

RETRY_MANIFEST = {
    "manifest_version": "1.0",
    "spec_version": "1.0",
    "globals": {
        "start_step": "gen",
        "budgets": {"max_total_attempts": 10, "max_attempts_per_step": 5, "max_cost_dollars": 1.0},
    },
    "steps": {
        "gen": {"agent_id": "counter", "post_specs": ["always_fail"]},
    },
    "edges": [
        {"from_step": "gen", "to_step": "__complete__", "when": "post_ok", "priority": 10},
        {"from_step": "gen", "to_step": "gen", "when": "failed('always_fail') and attempts('gen') < 3", "priority": 5},
        {"from_step": "gen", "to_step": "__fail__", "when": "true", "priority": 0},
    ],
}


# ── Tests ────────────────────────────────────────────────────────────────────

class TestOrchestratorBuilder:
    def test_build_requires_manifest(self):
        with pytest.raises(ValueError, match="Manifest is required"):
            OrchestratorBuilder().with_agent(EchoAgent()).build()

    def test_build_with_manifest_string(self):
        import json
        builder = (
            OrchestratorBuilder()
            .with_manifest_string(json.dumps(SINGLE_STEP_MANIFEST), format="json")
            .with_agent(EchoAgent())
            .with_spec(AlwaysPassSpec())
        )
        orchestrator = builder.build()
        assert orchestrator is not None

    def test_fluent_interface(self):
        import json
        builder = OrchestratorBuilder()
        result = builder.with_manifest_string(json.dumps(SINGLE_STEP_MANIFEST), format="json")
        assert result is builder  # Returns self for chaining

    def test_with_agents_plural(self):
        import json
        builder = (
            OrchestratorBuilder()
            .with_manifest_string(json.dumps(SINGLE_STEP_MANIFEST), format="json")
            .with_agents([EchoAgent()])
            .with_specs([AlwaysPassSpec()])
        )
        orchestrator = builder.build()
        assert orchestrator is not None


class TestOrchestratorRun:
    @pytest.mark.asyncio
    async def test_single_step_success(self):
        import json
        orchestrator = (
            OrchestratorBuilder()
            .with_manifest_string(json.dumps(SINGLE_STEP_MANIFEST), format="json")
            .with_agent(EchoAgent())
            .with_spec(AlwaysPassSpec())
            .build()
        )
        result = await orchestrator.run(initial_data={"input": "hello"})
        assert result.success is True
        assert result.terminal_state == COMPLETE
        assert result.total_steps_executed == 1
        assert result.final_context.get_data("result") == "hello"

    @pytest.mark.asyncio
    async def test_two_step_pipeline(self):
        import json
        orchestrator = (
            OrchestratorBuilder()
            .with_manifest_string(json.dumps(TWO_STEP_MANIFEST), format="json")
            .with_agent(EchoAgent())
            .with_spec(AlwaysPassSpec())
            .build()
        )
        result = await orchestrator.run(initial_data={"input": "data"})
        assert result.success is True
        assert result.total_steps_executed == 2

    @pytest.mark.asyncio
    async def test_retry_then_fail(self):
        import json
        counter = CountingAgent()
        orchestrator = (
            OrchestratorBuilder()
            .with_manifest_string(json.dumps(RETRY_MANIFEST), format="json")
            .with_agent(counter)
            .with_spec(AlwaysFailSpec())
            .build()
        )
        result = await orchestrator.run()
        assert result.success is False
        assert result.terminal_state == FAIL
        # Run 1: context data_keys=[] → fingerprint A → recorded
        # Run 2: context data_keys=["call_count"] → fingerprint B → recorded
        # Run 3 would have: data_keys=["call_count"] → fingerprint B again → loop detected
        # So loop detection kicks in after 2 executions
        assert counter.call_count == 2

    @pytest.mark.asyncio
    async def test_loop_detection_stops_identical_retries(self):
        """Loop detector prevents identical retries even if edges allow more."""
        import json
        manifest_data = {
            "manifest_version": "1.0",
            "spec_version": "1.0",
            "globals": {
                "start_step": "s1",
                "budgets": {"max_total_attempts": 100, "max_attempts_per_step": 100, "max_cost_dollars": 100.0},
            },
            "steps": {
                "s1": {"agent_id": "counter", "post_specs": ["always_fail"]},
            },
            "edges": [
                {"from_step": "s1", "to_step": "s1", "when": "failed('always_fail')", "priority": 5},
                {"from_step": "s1", "to_step": "__complete__", "when": "true", "priority": 0},
            ],
        }
        counter = CountingAgent()
        orchestrator = (
            OrchestratorBuilder()
            .with_manifest_string(json.dumps(manifest_data), format="json")
            .with_agent(counter)
            .with_spec(AlwaysFailSpec())
            .build()
        )
        result = await orchestrator.run()
        assert result.success is False
        assert "Loop detected" in result.summary
        # Despite 100 max attempts, loop detection limits to 2
        assert counter.call_count == 2

    @pytest.mark.asyncio
    async def test_agent_exception_recorded_in_trace(self):
        import json
        manifest_data = {
            "manifest_version": "1.0",
            "spec_version": "1.0",
            "globals": {"start_step": "s1"},
            "steps": {"s1": {"agent_id": "failing"}},
            "edges": [
                {"from_step": "s1", "to_step": "__complete__", "when": "true"},
            ],
        }
        orchestrator = (
            OrchestratorBuilder()
            .with_manifest_string(json.dumps(manifest_data), format="json")
            .with_agent(FailingAgent())
            .build()
        )
        result = await orchestrator.run()
        assert result.success is True  # Edge routes to __complete__ regardless
        assert len(result.final_context.trace) == 1
        assert result.final_context.trace[0].error is not None
        assert "Intentional failure" in result.final_context.trace[0].error

    @pytest.mark.asyncio
    async def test_context_delta_applied(self):
        import json
        orchestrator = (
            OrchestratorBuilder()
            .with_manifest_string(json.dumps(SINGLE_STEP_MANIFEST), format="json")
            .with_agent(EchoAgent())
            .with_spec(AlwaysPassSpec())
            .build()
        )
        result = await orchestrator.run(initial_data={"input": "test_value"})
        # EchoAgent writes {"result": value} to delta
        assert result.final_context.get_data("result") == "test_value"

    @pytest.mark.asyncio
    async def test_cost_tracking(self):
        import json
        orchestrator = (
            OrchestratorBuilder()
            .with_manifest_string(json.dumps(SINGLE_STEP_MANIFEST), format="json")
            .with_agent(EchoAgent())
            .with_spec(AlwaysPassSpec())
            .build()
        )
        result = await orchestrator.run()
        # EchoAgent returns cost=0.01
        assert result.final_context.budgets.current_cost == pytest.approx(0.01)

    @pytest.mark.asyncio
    async def test_trace_contains_step_entries(self):
        import json
        orchestrator = (
            OrchestratorBuilder()
            .with_manifest_string(json.dumps(TWO_STEP_MANIFEST), format="json")
            .with_agent(EchoAgent())
            .with_spec(AlwaysPassSpec())
            .build()
        )
        result = await orchestrator.run()
        assert len(result.final_context.trace) == 2
        assert result.final_context.trace[0].step_id == "step1"
        assert result.final_context.trace[1].step_id == "step2"

    @pytest.mark.asyncio
    async def test_on_step_complete_callback(self):
        import json
        callback_results = []

        def on_step(step_result: StepExecutionResult):
            callback_results.append(step_result.step_id)

        orchestrator = (
            OrchestratorBuilder()
            .with_manifest_string(json.dumps(TWO_STEP_MANIFEST), format="json")
            .with_agent(EchoAgent())
            .with_spec(AlwaysPassSpec())
            .on_step_complete(on_step)
            .build()
        )
        await orchestrator.run()
        assert callback_results == ["step1", "step2"]

    @pytest.mark.asyncio
    async def test_on_routing_callback(self):
        import json
        routing_log = []

        def on_route(from_step: str, to_step: str):
            routing_log.append((from_step, to_step))

        orchestrator = (
            OrchestratorBuilder()
            .with_manifest_string(json.dumps(TWO_STEP_MANIFEST), format="json")
            .with_agent(EchoAgent())
            .with_spec(AlwaysPassSpec())
            .on_routing(on_route)
            .build()
        )
        await orchestrator.run()
        assert routing_log == [("step1", "step2"), ("step2", "__complete__")]

    @pytest.mark.asyncio
    async def test_pre_spec_failure_skips_agent(self):
        """When pre-specs fail, agent should not execute."""
        import json

        class ContextHasRequiredField(Spec):
            @property
            def rule_id(self) -> str:
                return "has_required"

            @property
            def tags(self) -> tuple[str, ...]:
                return ("precondition",)

            def evaluate(self, context, candidate=None) -> SpecResult:
                if context.has_data("required_field"):
                    return SpecResult.ok(self.rule_id, tags=self.tags)
                return SpecResult.fail(self.rule_id, "Missing required field", tags=self.tags)

        manifest_data = {
            "manifest_version": "1.0",
            "spec_version": "1.0",
            "globals": {"start_step": "s1"},
            "steps": {"s1": {"agent_id": "counter", "pre_specs": ["has_required"]}},
            "edges": [
                {"from_step": "s1", "to_step": "__complete__", "when": "true"},
            ],
        }
        counter = CountingAgent()
        orchestrator = (
            OrchestratorBuilder()
            .with_manifest_string(json.dumps(manifest_data), format="json")
            .with_agent(counter)
            .with_spec(ContextHasRequiredField())
            .build()
        )
        # Don't provide required_field → pre-spec fails → agent skipped
        result = await orchestrator.run()
        assert counter.call_count == 0

    @pytest.mark.asyncio
    async def test_custom_run_id(self):
        import json
        orchestrator = (
            OrchestratorBuilder()
            .with_manifest_string(json.dumps(SINGLE_STEP_MANIFEST), format="json")
            .with_agent(EchoAgent())
            .with_spec(AlwaysPassSpec())
            .build()
        )
        result = await orchestrator.run(run_id="my-custom-run")
        assert result.final_context.run_id == "my-custom-run"


class TestWorkflowResult:
    @pytest.mark.asyncio
    async def test_to_dict(self):
        import json
        orchestrator = (
            OrchestratorBuilder()
            .with_manifest_string(json.dumps(SINGLE_STEP_MANIFEST), format="json")
            .with_agent(EchoAgent())
            .with_spec(AlwaysPassSpec())
            .build()
        )
        result = await orchestrator.run()
        d = result.to_dict()
        assert d["success"] is True
        assert d["terminal_state"] == "__complete__"
        assert "context" in d
        assert d["total_steps_executed"] == 1


class TestRunWorkflow:
    @pytest.mark.asyncio
    async def test_convenience_function(self, tmp_path):
        import json
        manifest_path = tmp_path / "workflow.json"
        manifest_path.write_text(json.dumps(SINGLE_STEP_MANIFEST))

        result = await run_workflow(
            manifest_path=str(manifest_path),
            agents=[EchoAgent()],
            specs=[AlwaysPassSpec()],
            initial_data={"input": "hello"},
        )
        assert result.success is True
        assert result.final_context.get_data("result") == "hello"
