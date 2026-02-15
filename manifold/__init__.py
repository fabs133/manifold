"""
Manifold - Contract-Driven Orchestration for Multi-Agent AI Systems.

Manifold enforces correctness in multi-agent workflows through:
- Specs: Pre/post/invariant/progress contracts that gate execution
- Router: Conditional edge evaluation based on spec outcomes
- Loop Detection: Semantic fingerprinting prevents identical retries
- Tracing: Complete audit trail of all decisions

Example usage:
    ```python
    from manifold import OrchestratorBuilder, Spec, SpecResult, Context

    # Define a spec
    class HasInputFile(Spec):
        rule_id = "has_input_file"

        def evaluate(self, context: Context, candidate=None):
            if context.has_data("input_file"):
                return SpecResult.ok(self.rule_id, "Input file present")
            return SpecResult.fail(
                self.rule_id,
                "Missing input file",
                suggested_fix="Provide input_file in context"
            )

    # Build and run orchestrator
    orchestrator = (
        OrchestratorBuilder()
        .with_manifest_file("workflow.yaml")
        .with_spec(HasInputFile())
        .build()
    )

    result = await orchestrator.run(initial_data={"input_file": "data.txt"})
    ```

Learn more: https://github.com/fabs133/manifold
"""

__version__ = "0.1.0"

# Core components
from manifold.core.context import (
    Context,
    ContextUpdater,
    create_context,
    Artifact,
    TraceEntry,
    ToolCall,
    SpecResultRef,
    Budgets,
)

from manifold.core.spec import (
    Spec,
    SpecResult,
    SpecEngine,
    # Common specs
    HasDataField,
    HasArtifact,
    BudgetNotExceeded,
    CandidateNotNone,
    CandidateHasAttribute,
)

from manifold.core.manifest import (
    Manifest,
    ManifestLoader,
    Step,
    Edge,
    RetryPolicy,
    GlobalConfig,
)

from manifold.core.router import (
    Router,
    ConditionEvaluator,
    RetryRouter,
    COMPLETE,
    FAIL,
)

from manifold.core.loop_detector import (
    LoopDetector,
    AttemptFingerprint,
)

from manifold.core.orchestrator import (
    Orchestrator,
    OrchestratorBuilder,
    WorkflowResult,
    StepExecutionResult,
    run_workflow,
)

__all__ = [
    # Version
    "__version__",

    # Context
    "Context",
    "ContextUpdater",
    "create_context",
    "Artifact",
    "TraceEntry",
    "ToolCall",
    "SpecResultRef",
    "Budgets",

    # Specs
    "Spec",
    "SpecResult",
    "SpecEngine",
    "HasDataField",
    "HasArtifact",
    "BudgetNotExceeded",
    "CandidateNotNone",
    "CandidateHasAttribute",

    # Manifest
    "Manifest",
    "ManifestLoader",
    "Step",
    "Edge",
    "RetryPolicy",
    "GlobalConfig",

    # Router
    "Router",
    "ConditionEvaluator",
    "RetryRouter",
    "COMPLETE",
    "FAIL",

    # Loop Detection
    "LoopDetector",
    "AttemptFingerprint",

    # Orchestrator
    "Orchestrator",
    "OrchestratorBuilder",
    "WorkflowResult",
    "StepExecutionResult",
    "run_workflow",
]
