"""
Orchestrator - Main execution loop for spec-driven workflows.

The Orchestrator is the "brain" that coordinates all components:
1. Loads manifest and initializes registries
2. Runs the execution loop:
   - Execute current step's agent
   - Evaluate specs (pre/post/invariant)
   - Record trace entry
   - Check for loops
   - Route to next step
3. Handles retries and budget enforcement
4. Returns final context with full trace

Key principle: The Orchestrator enforces contracts but doesn't
contain business logic. All logic is in agents and specs.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from manifold.core.context import (
    Context,
    ContextUpdater,
    TraceEntry,
    ToolCall as ContextToolCall,
    Budgets,
    create_context,
)
from manifold.core.spec import Spec, SpecEngine, SpecResult
from manifold.core.agent import Agent, AgentAdapter, AgentRegistry, AgentOutput
from manifold.core.manifest import Manifest, Step, ManifestLoader
from manifold.core.loop_detector import LoopDetector
from manifold.core.router import Router, COMPLETE, FAIL


@dataclass
class WorkflowResult:
    """
    Final result of a workflow run.

    Contains:
    - success: Whether workflow completed successfully
    - final_context: The context at termination
    - terminal_state: COMPLETE or FAIL
    - summary: Human-readable summary
    """

    success: bool
    final_context: Context
    terminal_state: str
    summary: str
    duration_ms: int = 0
    total_steps_executed: int = 0
    total_retries: int = 0

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "success": self.success,
            "terminal_state": self.terminal_state,
            "summary": self.summary,
            "duration_ms": self.duration_ms,
            "total_steps_executed": self.total_steps_executed,
            "total_retries": self.total_retries,
            "context": self.final_context.to_dict(),
        }


@dataclass
class StepExecutionResult:
    """Result of executing a single step."""

    step_id: str
    agent_output: AgentOutput | None
    spec_results: list[SpecResult]
    trace_entry: TraceEntry
    passed: bool
    error: str | None = None


class Orchestrator:
    """
    Main workflow execution engine.

    The Orchestrator:
    1. Manages the execution loop
    2. Coordinates agents, specs, and routing
    3. Enforces budgets and detects loops
    4. Maintains full execution trace

    Usage:
        orchestrator = Orchestrator(manifest, agents, specs)
        result = await orchestrator.run(initial_data)
    """

    def __init__(
        self,
        manifest: Manifest,
        agent_registry: AgentRegistry,
        spec_engine: SpecEngine,
        on_step_complete: Callable[[StepExecutionResult], None] | None = None,
        on_routing: Callable[[str, str], None] | None = None,
    ):
        """
        Initialize orchestrator.

        Args:
            manifest: Workflow definition
            agent_registry: Registry of available agents
            spec_engine: Engine with registered specs
            on_step_complete: Optional callback after each step
            on_routing: Optional callback on routing decisions
        """
        self._manifest = manifest
        self._agents = agent_registry
        self._specs = spec_engine
        self._router = Router(manifest)
        self._loop_detector = LoopDetector()
        self._on_step_complete = on_step_complete
        self._on_routing = on_routing

    async def run(
        self,
        initial_data: dict[str, Any] | None = None,
        run_id: str | None = None,
        budgets: Budgets | None = None,
    ) -> WorkflowResult:
        """
        Execute the complete workflow.

        Args:
            initial_data: Initial context data
            run_id: Optional run identifier
            budgets: Optional custom budget limits

        Returns:
            WorkflowResult with final state
        """
        start_time = datetime.now()

        # Initialize context
        if budgets is None:
            budgets = Budgets(
                max_total_attempts=self._manifest.globals.max_total_attempts,
                max_attempts_per_step=self._manifest.globals.max_attempts_per_step,
                max_cost_dollars=self._manifest.globals.max_cost_dollars,
            )

        context = create_context(
            run_id=run_id or f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            initial_data=initial_data,
            budgets=budgets,
        )

        # Get starting step
        current_step = self._manifest.get_start_step()
        steps_executed = 0
        retries = 0

        # Main execution loop
        while current_step not in (COMPLETE, FAIL):
            # Check global budget
            if context.budgets.is_total_budget_exceeded():
                return WorkflowResult(
                    success=False,
                    final_context=context,
                    terminal_state=FAIL,
                    summary=f"Budget exceeded after {steps_executed} steps",
                    duration_ms=self._elapsed_ms(start_time),
                    total_steps_executed=steps_executed,
                    total_retries=retries,
                )

            # Execute step
            step_result = await self._execute_step(current_step, context)
            steps_executed += 1

            # Update context with trace
            context = ContextUpdater.append_trace(context, step_result.trace_entry)

            # Apply agent's delta to context
            if step_result.agent_output and step_result.agent_output.delta:
                context = ContextUpdater.patch_data_many(context, step_result.agent_output.delta)

            # Add artifacts
            if step_result.agent_output:
                for artifact in step_result.agent_output.get_artifacts():
                    context = ContextUpdater.append_artifact(context, artifact)

            # Add cost
            if step_result.agent_output:
                context = ContextUpdater.add_cost(context, step_result.agent_output.cost)

            # Increment attempt counter
            context = ContextUpdater.increment_attempt(context, current_step)

            # Callback
            if self._on_step_complete:
                self._on_step_complete(step_result)

            # Check for loops
            fingerprint = self._loop_detector.compute_fingerprint(
                step_result.trace_entry, context, initial_data
            )

            if self._loop_detector.is_loop(fingerprint):
                return WorkflowResult(
                    success=False,
                    final_context=context,
                    terminal_state=FAIL,
                    summary=f"Loop detected at step '{current_step}'",
                    duration_ms=self._elapsed_ms(start_time),
                    total_steps_executed=steps_executed,
                    total_retries=retries,
                )

            self._loop_detector.record(fingerprint)

            # Route to next step
            next_step = self._router.route(current_step, context, step_result.trace_entry)

            # Track retries
            if next_step == current_step:
                retries += 1

            # Callback
            if self._on_routing:
                self._on_routing(current_step, next_step)

            current_step = next_step

        # Workflow complete
        success = current_step == COMPLETE
        return WorkflowResult(
            success=success,
            final_context=context,
            terminal_state=current_step,
            summary=f"Workflow {'completed' if success else 'failed'} after {steps_executed} steps",
            duration_ms=self._elapsed_ms(start_time),
            total_steps_executed=steps_executed,
            total_retries=retries,
        )

    async def _execute_step(self, step_id: str, context: Context) -> StepExecutionResult:
        """
        Execute a single step.

        Args:
            step_id: Step to execute
            context: Current context

        Returns:
            StepExecutionResult with outcome
        """
        step = self._manifest.get_step_required(step_id)
        start_time = datetime.now()
        attempt = context.budgets.get_step_attempts(step_id) + 1

        # Evaluate pre-specs
        pre_results = self._specs.evaluate(list(step.pre_specs), context)

        if not self._specs.all_passed(pre_results):
            # Pre-conditions failed
            return self._create_step_result(
                step_id=step_id,
                attempt=attempt,
                start_time=start_time,
                spec_results=pre_results,
                agent_output=None,
                error="Pre-conditions not met",
            )

        # Prepare input data
        input_data = self._prepare_input(step, context)

        # Execute agent
        agent = self._agents.get_required(step.agent_id)
        agent_output: AgentOutput | None = None
        error: str | None = None

        try:
            agent_output = await agent.execute(context, input_data)
        except Exception as e:
            error = str(e)

        # Evaluate post-specs
        post_results = self._specs.evaluate(
            list(step.post_specs), context, agent_output.output if agent_output else None
        )

        # Evaluate invariant specs (step-level + global)
        invariant_ids = list(step.invariant_specs) + list(self._manifest.globals.invariant_specs)
        invariant_results = self._specs.evaluate(
            invariant_ids, context, agent_output.output if agent_output else None
        )

        # Combine all spec results
        all_results = pre_results + post_results + invariant_results

        return self._create_step_result(
            step_id=step_id,
            attempt=attempt,
            start_time=start_time,
            spec_results=all_results,
            agent_output=agent_output,
            error=error,
        )

    def _prepare_input(self, step: Step, context: Context) -> dict[str, Any] | None:
        """Prepare input data for agent based on step's input_mapping."""
        if not step.input_mapping:
            return None

        input_data = {}
        for target_key, source_key in step.input_mapping.items():
            if context.has_data(source_key):
                input_data[target_key] = context.get_data(source_key)

        return input_data if input_data else None

    def _create_step_result(
        self,
        step_id: str,
        attempt: int,
        start_time: datetime,
        spec_results: list[SpecResult],
        agent_output: AgentOutput | None,
        error: str | None,
    ) -> StepExecutionResult:
        """Create a StepExecutionResult with trace entry."""
        duration_ms = self._elapsed_ms(start_time)

        # Convert spec results to refs
        spec_refs = tuple(sr.to_trace_ref() for sr in spec_results)

        # Get tool calls
        tool_calls = tuple(agent_output.get_tool_calls()) if agent_output else ()
        # Convert ToolCall from agent module to context module format
        context_tool_calls = tuple(
            ContextToolCall(
                name=tc.name,
                args=tc.args,
                result=tc.result,
                duration_ms=tc.duration_ms,
                timestamp=tc.timestamp,
            )
            for tc in tool_calls
        )

        trace_entry = TraceEntry(
            timestamp=start_time,
            step_id=step_id,
            attempt=attempt,
            agent_output=agent_output.output if agent_output else None,
            tool_calls=context_tool_calls,
            spec_results=spec_refs,
            duration_ms=duration_ms,
            error=error,
        )

        passed = all(sr.passed for sr in spec_results) and error is None

        return StepExecutionResult(
            step_id=step_id,
            agent_output=agent_output,
            spec_results=spec_results,
            trace_entry=trace_entry,
            passed=passed,
            error=error,
        )

    def _elapsed_ms(self, start_time: datetime) -> int:
        """Calculate elapsed milliseconds."""
        delta = datetime.now() - start_time
        return int(delta.total_seconds() * 1000)


class OrchestratorBuilder:
    """
    Builder for creating Orchestrator instances.

    Provides a fluent interface for configuration.

    Usage:
        orchestrator = (
            OrchestratorBuilder()
            .with_manifest_file("workflow.yaml")
            .with_agent(MyAgent())
            .with_spec(MySpec())
            .build()
        )
    """

    def __init__(self):
        self._manifest: Manifest | None = None
        self._agents: list[Agent | AgentAdapter] = []
        self._specs: list[Spec] = []
        self._on_step_complete: Callable | None = None
        self._on_routing: Callable | None = None

    def with_manifest(self, manifest: Manifest) -> "OrchestratorBuilder":
        """Set manifest directly."""
        self._manifest = manifest
        return self

    def with_manifest_file(self, path: str) -> "OrchestratorBuilder":
        """Load manifest from file."""
        self._manifest = ManifestLoader.load(path)
        return self

    def with_manifest_string(self, content: str, format: str = "yaml") -> "OrchestratorBuilder":
        """Load manifest from string."""
        self._manifest = ManifestLoader.load_string(content, format)
        return self

    def with_agent(self, agent: Agent | AgentAdapter) -> "OrchestratorBuilder":
        """Add an agent."""
        self._agents.append(agent)
        return self

    def with_agents(self, agents: list[Agent | AgentAdapter]) -> "OrchestratorBuilder":
        """Add multiple agents."""
        self._agents.extend(agents)
        return self

    def with_spec(self, spec: Spec) -> "OrchestratorBuilder":
        """Add a spec."""
        self._specs.append(spec)
        return self

    def with_specs(self, specs: list[Spec]) -> "OrchestratorBuilder":
        """Add multiple specs."""
        self._specs.extend(specs)
        return self

    def on_step_complete(
        self, callback: Callable[[StepExecutionResult], None]
    ) -> "OrchestratorBuilder":
        """Set step completion callback."""
        self._on_step_complete = callback
        return self

    def on_routing(self, callback: Callable[[str, str], None]) -> "OrchestratorBuilder":
        """Set routing callback."""
        self._on_routing = callback
        return self

    def build(self) -> Orchestrator:
        """Build the orchestrator."""
        if self._manifest is None:
            raise ValueError("Manifest is required")

        # Build registries
        agent_registry = AgentRegistry()
        agent_registry.register_many(self._agents)

        spec_engine = SpecEngine()
        spec_engine.register_many(self._specs)

        return Orchestrator(
            manifest=self._manifest,
            agent_registry=agent_registry,
            spec_engine=spec_engine,
            on_step_complete=self._on_step_complete,
            on_routing=self._on_routing,
        )


# Convenience function for simple workflows
async def run_workflow(
    manifest_path: str,
    agents: list[Agent | AgentAdapter],
    specs: list[Spec],
    initial_data: dict[str, Any] | None = None,
) -> WorkflowResult:
    """
    Run a workflow from a manifest file.

    Convenience function for simple use cases.

    Args:
        manifest_path: Path to manifest YAML/JSON
        agents: List of agents to register
        specs: List of specs to register
        initial_data: Initial context data

    Returns:
        WorkflowResult
    """
    orchestrator = (
        OrchestratorBuilder()
        .with_manifest_file(manifest_path)
        .with_agents(agents)
        .with_specs(specs)
        .build()
    )

    return await orchestrator.run(initial_data)
