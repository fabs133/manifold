"""
manifold.testing.harness
~~~~~~~~~~~~~~~~~~~~~~~~
HMMVTestHarness — the "fill in your models and go" preset.

Usage
-----
    from manifold.testing import HMMVTestHarness
    from manifold.testing.stores import SQLiteBaselineStore

    harness = HMMVTestHarness(
        models=["gpt-4o", "gemini-flash", "llama-3.3", "mistral-small"],
        workflow_manifest="classify.yaml",
        baseline_store=SQLiteBaselineStore("baseline.db"),
    )

    await harness.setup()
    result = await harness.run({"name": "Caritas Berlin", "type": "welfare"})

    print(result.regime)          # "convergent" | "drift" | "early" | "novel_class"
    print(result.consensus_score) # float
    print(result.drift_signal)    # DriftSignal | None

Design
------
The harness owns the wiring between all components:

  1. Builds EventBus + EventConsumer
  2. Creates ConvergenceMonitor with the user's baseline store
  3. Wraps it in a Spec via make_convergence_spec()
  4. Builds the Orchestrator via OrchestratorBuilder
  5. After each run:
     a. Drains pending records → writes to baseline store
     b. Drains pending signals → stores signal → emits RUN_COMPLETED event
     c. Refreshes baseline cache for next run
  6. Exposes hooks for human review (on_proposal_ready callback)

The harness does NOT decide what happens to proposals — that is the
EventConsumer's job. The harness just emits events and wires the plumbing.

Correction runner
-----------------
The harness accepts an optional `correction_runner` argument. If None,
a NoOpCorrectionRunner is used which logs signals but produces no proposals.
Replace with a real implementation when the correction workflow is built.
"""

from __future__ import annotations

import asyncio
import logging
import statistics
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from manifold.testing.convergence import (
    ConvergenceConfig,
    ConvergenceMonitor,
    make_convergence_spec,
)
from manifold.testing.events import (
    Event,
    EventBus,
    EventConsumer,
    EventType,
    payload_run_completed,
)
from manifold.testing.models import DriftSignal, SpecProposal
from manifold.testing.stores import (
    InMemoryProposalStore,
    InMemorySnapshotStore,
    InMemorySpecRegistry,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# HMMVResult — what harness.run() returns
# ---------------------------------------------------------------------------


@dataclass
class HMMVResult:
    """
    Result of a single harness run.

    Fields
    ------
    run_id          : unique run identifier
    success         : whether the primary workflow completed
    regime          : "early" | "novel_class" | "convergent" | "drift"
    consensus_score : median across model scores (None if workflow failed)
    model_scores    : {model_id: score}
    inter_model_mad : mean absolute deviation
    input_class     : cluster label assigned to this input
    drift_signal    : populated if regime == "drift", else None
    workflow_summary: summary string from the underlying WorkflowResult
    error           : populated if success == False
    """

    run_id: str
    success: bool
    regime: str
    consensus_score: float | None
    model_scores: dict[str, float]
    inter_model_mad: float
    input_class: str
    drift_signal: DriftSignal | None = None
    workflow_summary: str = ""
    error: str | None = None


# ---------------------------------------------------------------------------
# No-op correction runner (placeholder)
# ---------------------------------------------------------------------------


class NoOpCorrectionRunner:
    """
    Placeholder correction runner.

    Logs drift signals but produces no SpecProposal. Replace with a real
    implementation backed by a correction workflow manifest.
    """

    async def run(self, signal: DriftSignal) -> SpecProposal | None:
        logger.warning(
            "NoOpCorrectionRunner received drift signal %s (type=%s, class=%s). "
            "No proposal generated — wire up a real correction runner.",
            signal.signal_id,
            signal.drift_type.value,
            signal.input_class,
        )
        return None


# ---------------------------------------------------------------------------
# HMMVTestHarness
# ---------------------------------------------------------------------------


class HMMVTestHarness:
    """
    Preset harness for Heterogeneous Multi-Model Validation workflows.

    Minimal required arguments:
        models              — list of model identifiers (used to name agents)
        workflow_manifest   — path to your Manifold workflow YAML
        baseline_store      — BaselineStore implementation

    Everything else has sensible defaults.

    Lifecycle
    ---------
    1. Instantiate
    2. Call await harness.setup()     ← initialises stores and caches
    3. Call await harness.run(input)  ← as many times as needed
    4. Human reviews proposals via harness.pending_proposals()
    5. Call await harness.approve_proposal(id, notes) to apply a proposal
    """

    def __init__(
        self,
        models: list[str],
        workflow_manifest: str,
        baseline_store: Any,
        *,
        # Optional stores (in-memory defaults for development)
        snapshot_store: Any | None = None,
        proposal_store: Any | None = None,
        spec_registry: Any | None = None,
        # Correction runner (no-op by default)
        correction_runner: Any | None = None,
        # Convergence tuning
        config: ConvergenceConfig | None = None,
        # Snapshot frequency
        snapshot_interval: int = 100,
        # Hooks
        on_proposal_ready: Callable[[SpecProposal], Awaitable[None]] | None = None,
        on_drift_detected: Callable[[DriftSignal], Awaitable[None]] | None = None,
    ) -> None:
        self._models = models
        self._manifest_path = workflow_manifest
        self._baseline = baseline_store
        self._snapshots = snapshot_store or InMemorySnapshotStore()
        self._proposals = proposal_store or InMemoryProposalStore()
        self._registry = spec_registry or InMemorySpecRegistry()
        self._correction_runner = correction_runner or NoOpCorrectionRunner()
        self._config = config or ConvergenceConfig()
        self._snapshot_interval = snapshot_interval
        self._on_proposal_ready = on_proposal_ready
        self._on_drift_detected = on_drift_detected

        # Built during setup()
        self._monitor: ConvergenceMonitor | None = None
        self._orchestrator: Any | None = None
        self._bus: EventBus | None = None
        self._consumer: EventConsumer | None = None
        self._ready = False

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    async def setup(self) -> None:
        """
        Initialise all components.

        Must be called before run(). Idempotent.
        """
        if self._ready:
            return

        # Initialise baseline store if it supports it
        if hasattr(self._baseline, "initialise"):
            await self._baseline.initialise()

        # Build event bus
        self._bus = EventBus()

        # Build correction runner wrapper that emits correction events
        self._consumer = EventConsumer(
            baseline_store=self._baseline,
            snapshot_store=self._snapshots,
            proposal_store=self._proposals,
            spec_registry=self._registry,
            correction_runner=self._correction_runner,
            bus=self._bus,
            snapshot_interval=self._snapshot_interval,
        )

        # Wire user callbacks
        if self._on_proposal_ready:

            async def _proposal_handler(event: Event) -> None:
                proposal = SpecProposal.from_dict(event.payload["proposal"])
                await self._on_proposal_ready(proposal)  # type: ignore[misc]

            self._bus.subscribe(EventType.PROPOSAL_READY, _proposal_handler)

        if self._on_drift_detected:

            async def _drift_handler(event: Event) -> None:
                signal = DriftSignal.from_dict(event.payload["drift_signal"])
                await self._on_drift_detected(signal)  # type: ignore[misc]

            self._bus.subscribe(EventType.DRIFT_DETECTED, _drift_handler)

        # Get current spec versions from registry for record annotation
        spec_versions = await self._registry.current_versions()

        # Build ConvergenceMonitor
        self._monitor = ConvergenceMonitor(
            baseline_store=self._baseline,
            config=self._config,
            spec_versions=spec_versions,
        )

        # Refresh cache before building orchestrator
        await self._refresh_cache()

        # Build orchestrator
        self._orchestrator = self._build_orchestrator()

        self._ready = True
        logger.info(
            "HMMVTestHarness ready: %d models, manifest=%s",
            len(self._models),
            self._manifest_path,
        )

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    async def run(
        self,
        input_data: dict[str, Any],
        input_class: str | None = None,
        cluster_version: str | None = None,
    ) -> HMMVResult:
        """
        Run the primary workflow on a single input.

        Args
        ----
        input_data      Raw input dict (will be fingerprinted).
        input_class     Override cluster label. If None, must be set in
                        input_data or populated by a clustering step in
                        the workflow manifest.
        cluster_version Version tag of the clustering model.

        Returns
        -------
        HMMVResult with convergence info and optional DriftSignal.
        """
        if not self._ready:
            await self.setup()

        # Refresh baseline cache before each run
        await self._refresh_cache()

        # Merge input_class into initial data if provided
        initial: dict[str, Any] = {
            self._config.record_input_field: input_data,
            **input_data,
        }
        if input_class:
            initial[self._config.record_class_field] = input_class
        if cluster_version:
            initial["cluster_version"] = cluster_version

        # Run the orchestrator
        run_id = str(uuid.uuid4())
        try:
            from manifold.core.context import create_context

            create_context(run_id=run_id, initial_data=initial)
            assert self._orchestrator is not None, "Call setup() before run()"
            workflow_result = await self._orchestrator.run(initial_data=initial)
        except Exception as e:
            logger.error("Orchestrator failed: %s", e, exc_info=True)
            return HMMVResult(
                run_id=run_id,
                success=False,
                regime="error",
                consensus_score=None,
                model_scores={},
                inter_model_mad=0.0,
                input_class=input_class or "unknown",
                error=str(e),
            )

        # Drain convergence monitor
        assert self._monitor is not None, "Call setup() before run()"
        signals = self._monitor.drain_signals()
        records = self._monitor.drain_records()

        had_drift = len(signals) > 0
        drift_signal = signals[0] if signals else None
        convergence_r = records[0] if records else None

        # Store signals and records
        for sig in signals:
            # Enrich: add representative fingerprints from baseline
            fps = await self._baseline.sample_fingerprints_for_class(sig.input_class, n=5)
            from dataclasses import replace

            sig = replace(sig, representative_fps=fps, triggering_input=input_data)
            await self._baseline.append_signal(sig)

        # Emit RUN_COMPLETED event (triggers baseline update or correction workflow)
        event = Event.create(
            EventType.RUN_COMPLETED,
            source="hmmv_harness",
            payload=payload_run_completed(
                run_id=run_id,
                success=workflow_result.success,
                had_drift=had_drift,
                drift_signal_id=drift_signal.signal_id if drift_signal else None,
                convergence_record=convergence_r,
            ),
        )
        await self._bus.emit(event)  # type: ignore[union-attr]

        # Give event tasks a cycle to start
        await asyncio.sleep(0)

        # Extract convergence result from monitor output
        model_scores = workflow_result.final_context.get_data(self._config.record_mad_field, {})
        detected_class = workflow_result.final_context.get_data(
            self._config.record_class_field, input_class or "unknown"
        )

        scores_list = list(model_scores.values())
        mad = _compute_mad_sync(scores_list)
        consensus = statistics.median(scores_list) if scores_list else None

        # Determine regime from most recent spec result
        regime = self._extract_regime(workflow_result)

        return HMMVResult(
            run_id=run_id,
            success=workflow_result.success,
            regime=regime,
            consensus_score=consensus,
            model_scores=model_scores,
            inter_model_mad=mad,
            input_class=detected_class,
            drift_signal=drift_signal,
            workflow_summary=workflow_result.summary,
        )

    # ------------------------------------------------------------------
    # Proposal review API
    # ------------------------------------------------------------------

    async def pending_proposals(self) -> list[SpecProposal]:
        """Return all SpecProposals awaiting human review."""
        return await self._proposals.pending_proposals()

    async def approve_proposal(
        self,
        proposal_id: str,
        reviewer_notes: str = "",
    ) -> None:
        """
        Approve a proposal. This:
        1. Marks it approved in the proposal store
        2. Applies it to the spec registry
        3. Marks affected baseline records as stale
        4. Refreshes the monitor's spec_versions
        """
        assert self._bus is not None, "Call setup() before approve_proposal()"
        await self._bus.emit(
            Event.create(
                EventType.PROPOSAL_APPROVED,
                source="harness.approve_proposal",
                payload={"proposal_id": proposal_id, "reviewer_notes": reviewer_notes},
            )
        )
        await asyncio.sleep(0)  # let EventConsumer process
        # Refresh spec versions in monitor
        assert self._monitor is not None
        self._monitor._spec_versions = await self._registry.current_versions()

    async def reject_proposal(
        self,
        proposal_id: str,
        reviewer_notes: str = "",
    ) -> None:
        """Reject a proposal without applying it."""
        assert self._bus is not None, "Call setup() before reject_proposal()"
        await self._bus.emit(
            Event.create(
                EventType.PROPOSAL_REJECTED,
                source="harness.reject_proposal",
                payload={"proposal_id": proposal_id, "reviewer_notes": reviewer_notes},
            )
        )

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    async def baseline_stats(self) -> dict:
        """Return a summary of current baseline state."""
        total = await self._baseline.total_records()
        snapshot = await self._snapshots.latest()
        return {
            "total_records": total,
            "drift_detection_active": total >= self._config.min_baseline_size,
            "latest_snapshot_id": snapshot.snapshot_id if snapshot else None,
            "latest_snapshot_records": snapshot.total_records if snapshot else 0,
            "pending_proposals": len(await self._proposals.pending_proposals()),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _refresh_cache(self) -> None:
        """Update the convergence monitor's synchronous baseline cache."""
        if self._monitor is None:
            return

        total = await self._baseline.total_records()
        snapshot = await self._snapshots.latest()

        if snapshot and snapshot.total_records > 0:
            class_mads = snapshot.mad_by_class
            class_counts = snapshot.records_by_class
        else:
            # No snapshot yet — compute from raw records (slower, only in early regime)
            class_mads, class_counts = await self._compute_class_stats()

        self._monitor.update_baseline_cache(total, class_mads, class_counts)

    async def _compute_class_stats(self) -> tuple[dict[str, float], dict[str, int]]:
        """Compute per-class MAD stats directly from baseline records (no snapshot)."""
        # In early regime this is called infrequently, so the cost is acceptable.
        # Once a snapshot exists, _refresh_cache uses it instead.
        # This is a best-effort fallback — only works for InMemoryBaselineStore.
        if not hasattr(self._baseline, "_records"):
            return {}, {}
        records = self._baseline._records
        from collections import defaultdict

        by_class: dict[str, list] = defaultdict(list)
        for r in records:
            by_class[r.input_class].append(r)
        mads = {c: statistics.mean(r.inter_model_mad for r in rs) for c, rs in by_class.items()}
        counts = {c: len(rs) for c, rs in by_class.items()}
        return mads, counts

    def _build_orchestrator(self) -> Any:
        """Build the Manifold orchestrator with the convergence spec injected."""
        try:
            from manifold import OrchestratorBuilder
        except ImportError as e:
            raise ImportError(
                "manifold must be installed to use HMMVTestHarness. " "pip install manifold-ai"
            ) from e

        spec = make_convergence_spec(self._monitor)  # type: ignore[arg-type]

        builder = OrchestratorBuilder().with_manifest_file(self._manifest_path).with_spec(spec)
        return builder.build()

    def _extract_regime(self, workflow_result: Any) -> str:
        """
        Pull the regime string from the convergence monitor's last spec result.

        Falls back to "convergent" if the spec result is not findable
        (e.g. the workflow failed before the invariant ran).
        """
        ctx = workflow_result.final_context
        for entry in reversed(ctx.trace):
            for spec_ref in entry.spec_results:
                if spec_ref.rule_id == "convergence_monitor":
                    return str(spec_ref.data.get("regime", "convergent"))
        return "convergent"


# ---------------------------------------------------------------------------
# Convenience (standalone, without manifold installed)
# ---------------------------------------------------------------------------


def _compute_mad_sync(values: list[float]) -> float:
    if not values:
        return 0.0
    mean = statistics.mean(values)
    return statistics.mean(abs(v - mean) for v in values)
