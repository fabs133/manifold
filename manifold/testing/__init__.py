"""
manifold.testing
~~~~~~~~~~~~~~~~
Adaptive Convergence Testing — Heterogeneous Multi-Model Validation preset.

Quick start
-----------
    from manifold.testing import HMMVTestHarness, CorrectionRunner
    from manifold.testing.stores import SQLiteBaselineStore

    async def call_llm(prompt): ...          # wire to Anthropic/OpenAI/etc.
    async def run_model(inp, hint, mid): ... # wire to your model clients

    harness = HMMVTestHarness(
        models=["gpt-4o", "gemini-flash", "llama-3.3", "mistral-small"],
        workflow_manifest="classify.yaml",
        baseline_store=SQLiteBaselineStore("baseline.db"),
        correction_runner=CorrectionRunner(call_llm, run_model,
            model_ids=[...]),
    )

    await harness.setup()
    result = await harness.run({"name": "Caritas Berlin", "type": "welfare"})

Standalone example (no manifold dependency on Orchestrator):
    python3 -m manifold.testing.example.end_to_end
"""

from manifold.testing.models import (
    ConvergenceRecord,
    BaselineSnapshot,
    DriftSignal,
    DriftType,
    SpecProposal,
    ProposalStatus,
    ReviewStatus,
)
from manifold.testing.convergence import (
    ConvergenceConfig,
    ConvergenceMonitor,
    make_convergence_spec,
)
from manifold.testing.correction import (
    CorrectionRunner,
    CorrectionAnalysis,
    Hypothesis,
    ValidationResult,
    analyze,
    generate_hypothesis,
    validate,
)
from manifold.testing.events import Event, EventBus, EventConsumer, EventType
from manifold.testing.stores import (
    InMemoryBaselineStore,
    InMemorySnapshotStore,
    InMemoryProposalStore,
    InMemorySpecRegistry,
    SQLiteBaselineStore,
)
from manifold.testing.harness import HMMVTestHarness, HMMVResult, NoOpCorrectionRunner

__all__ = [
    # models
    "ConvergenceRecord", "BaselineSnapshot", "DriftSignal", "DriftType",
    "SpecProposal", "ProposalStatus", "ReviewStatus",
    # convergence
    "ConvergenceConfig", "ConvergenceMonitor", "make_convergence_spec",
    # correction
    "CorrectionRunner", "CorrectionAnalysis", "Hypothesis", "ValidationResult",
    "analyze", "generate_hypothesis", "validate",
    # events
    "Event", "EventBus", "EventConsumer", "EventType",
    # stores
    "InMemoryBaselineStore", "InMemorySnapshotStore",
    "InMemoryProposalStore", "InMemorySpecRegistry",
    "SQLiteBaselineStore",
    # harness
    "HMMVTestHarness", "HMMVResult", "NoOpCorrectionRunner",
]
