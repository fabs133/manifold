"""
Simple Manifold Example - Data Processing Workflow

This example demonstrates:
- Custom specs (pre/post conditions)
- Simple agent implementation
- Manifest-driven workflow
- Loop detection
- Complete tracing
"""

import asyncio
from dataclasses import dataclass
from manifold import (
    Context, Spec, SpecResult, Agent, AgentOutput,
    OrchestratorBuilder, create_context
)


# ─── SPECS ───────────────────────────────────────────────────────────────


class HasInputData(Spec):
    """Pre-condition: input_data must exist."""
    
    @property
    def rule_id(self) -> str:
        return "has_input_data"
    
    @property
    def tags(self):
        return ("precondition", "data")
    
    def evaluate(self, context: Context, candidate=None) -> SpecResult:
        if context.has_data("input_data"):
            return SpecResult.ok(
                self.rule_id,
                "Input data is present",
                tags=self.tags
            )
        return SpecResult.fail(
            self.rule_id,
            "Missing input_data",
            suggested_fix="Provide 'input_data' in initial context",
            tags=self.tags
        )


class OutputNotEmpty(Spec):
    """Post-condition: output must not be empty."""
    
    @property
    def rule_id(self) -> str:
        return "output_not_empty"
    
    @property
    def tags(self):
        return ("postcondition", "output")
    
    def evaluate(self, context: Context, candidate=None) -> SpecResult:
        if candidate and len(str(candidate)) > 0:
            return SpecResult.ok(
                self.rule_id,
                f"Output produced: {len(str(candidate))} chars",
                tags=self.tags
            )
        return SpecResult.fail(
            self.rule_id,
            "Output is empty or None",
            suggested_fix="Ensure agent produces non-empty output",
            tags=self.tags
        )


# ─── AGENTS ──────────────────────────────────────────────────────────────


class DataProcessorAgent(Agent):
    """Simple agent that processes input data."""
    
    @property
    def agent_id(self) -> str:
        return "data_processor"
    
    async def execute(self, context: Context, input_data=None) -> AgentOutput:
        """Process the input data."""
        # Get input from context
        raw_data = context.get_data("input_data", "")
        
        # Simple processing: uppercase and add suffix
        processed = f"{raw_data.upper()} - PROCESSED"
        
        return AgentOutput(
            output=processed,
            delta={"processed_data": processed},
            cost=0.001  # Minimal cost for demo
        )


# ─── MAIN ────────────────────────────────────────────────────────────────


async def main():
    """Run the example workflow."""
    
    print("=" * 60)
    print("Manifold Simple Example - Data Processing Workflow")
    print("=" * 60)
    print()
    
    # Build orchestrator
    print("Building orchestrator...")
    orchestrator = (
        OrchestratorBuilder()
        .with_manifest_file("examples/simple_example/workflow.yaml")
        .with_spec(HasInputData())
        .with_spec(OutputNotEmpty())
        .with_agent(DataProcessorAgent())
        .build()
    )
    print("[OK] Orchestrator built")
    print()
    
    # Run workflow
    print("Running workflow...")
    result = await orchestrator.run(
        initial_data={"input_data": "hello world"}
    )
    
    print()
    print("=" * 60)
    print("RESULTS")
    print("=" * 60)
    print(f"Success: {result.success}")
    print(f"Terminal State: {result.terminal_state}")
    print(f"Steps Executed: {result.total_steps_executed}")
    print(f"Total Retries: {result.total_retries}")
    print(f"Duration: {result.duration_ms}ms")
    print()
    
    # Show final data
    print("Final Context Data:")
    for key, value in result.final_context.data.items():
        print(f"  {key}: {value}")
    print()
    
    # Show trace
    print("Execution Trace:")
    for i, entry in enumerate(result.final_context.trace, 1):
        print(f"  {i}. {entry.step_id} (attempt {entry.attempt})")
        print(f"     - Output: {entry.agent_output}")
        print(f"     - Specs: {len(entry.spec_results)} evaluated")
        passed = sum(1 for sr in entry.spec_results if sr.passed)
        print(f"     - Passed: {passed}/{len(entry.spec_results)}")
        if entry.error:
            print(f"     - Error: {entry.error}")
    print()
    
    print("=" * 60)
    print("Example completed successfully!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
