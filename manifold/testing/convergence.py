"""
manifold.testing.convergence
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
ConvergenceMonitor — an invariant Spec that tracks inter-model agreement.

Design constraint
-----------------
Specs in Manifold are pure: they cannot mutate Context. They can only
return a SpecResult (with optional data payload).

To bridge the gap between "spec detected drift" and "event needs to be
emitted", the ConvergenceMonitor maintains an internal signal queue.
After each orchestrator run the harness calls `drain_signals()` to
collect any pending DriftSignals and emit the appropriate events.

This keeps the spec system clean while giving the harness full control
over what happens next.

Invariant behaviour
-------------------
The monitor ALWAYS returns SpecResult.ok() — drift is not a workflow
failure. It is a side-channel signal. The primary workflow completes
and produces its consensus result regardless.

Regimes (emergent, not configured)
-----------------------------------
EARLY   total_records < min_baseline_size
        → Detection inactive. Every convergent run silently adds to baseline.

MIDDLE  baseline active, but < 10 records for this input class
        → Class is new. Pass silently, mark as novel, accumulate data.

MATURE  ≥ 10 records for input class
        → Compare observed MAD against class baseline.
          If observed > expected × drift_multiplier → drift signal.
          Otherwise → append to baseline.
"""

from __future__ import annotations

import statistics
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from manifold.testing.models import (
    ConvergenceRecord,
    DriftSignal,
    DriftType,
    _compute_mad,
    _fingerprint,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConvergenceConfig:
    """
    Tuning parameters for the convergence monitor.

    Defaults are intentionally conservative — the system will spend more
    time in the early regime, but once drift detection activates, it is
    well-calibrated.

    Attributes
    ----------
    min_baseline_size   Total records needed before drift detection activates.
                        Set high at start. Once crossed, never needs adjustment.
    drift_multiplier    Observed MAD must exceed expected_MAD × this value to
                        trigger a drift signal. 2.5 = 150% above baseline.
    outlier_threshold   How many σ a single model must be from the others
                        to be classified as MODEL_OUTLIER vs CRITERIA_GAP.
    min_class_records   Records per input_class before per-class MAD is used.
                        Below this: class is treated as novel.
    record_mad_field    Context data key holding the per-model score dict.
    record_class_field  Context data key holding the input_class label.
    record_input_field  Context data key holding the raw input (for fingerprint).
    record_output_field Context data key holding raw per-model outputs (optional).
    """

    min_baseline_size: int = 500
    drift_multiplier: float = 2.5
    outlier_threshold: float = 2.0  # σ
    min_class_records: int = 10
    record_mad_field: str = "model_scores"
    record_class_field: str = "input_class"
    record_input_field: str = "input_data"
    record_output_field: str = "model_outputs"


# ---------------------------------------------------------------------------
# ConvergenceMonitor
# ---------------------------------------------------------------------------


class ConvergenceMonitor:
    """
    Invariant Spec that monitors inter-model convergence.

    This class is NOT a subclass of manifold.core.spec.Spec because it
    cannot import from the manifold package at this layer (to keep the
    testing module usable standalone). The HMMVTestHarness wraps it in
    an adapter that satisfies the Spec protocol.

    To use it with a raw OrchestratorBuilder, use ConvergenceMonitorSpec
    (the adapter defined below), which requires manifold to be installed.

    Internal state
    --------------
    _baseline_store     AsyncBaselineStore protocol (injected)
    _config             ConvergenceConfig
    _pending_signals    deque of DriftSignal, drained by harness after each run
    _pending_records    deque of ConvergenceRecord, flushed to store after each run
    _snapshot_total     how many records existed at last snapshot check
    """

    rule_id = "convergence_monitor"

    def __init__(
        self,
        baseline_store: Any,
        config: ConvergenceConfig | None = None,
        spec_versions: dict[str, str] | None = None,
    ) -> None:
        self._baseline = baseline_store
        self._config = config or ConvergenceConfig()
        self._spec_versions = spec_versions or {}
        self._pending_signals: deque[DriftSignal] = deque()
        self._pending_records: deque[ConvergenceRecord] = deque()

        # Synchronous snapshot of baseline state for evaluate()
        # Updated by harness before each run via update_baseline_cache()
        self._cached_total: int = 0
        self._cached_class_mads: dict[str, float] = {}
        self._cached_class_count: dict[str, int] = {}

    # ------------------------------------------------------------------
    # Cache management (called by harness, sync)
    # ------------------------------------------------------------------

    def update_baseline_cache(
        self,
        total_records: int,
        class_mads: dict[str, float],
        class_counts: dict[str, int],
    ) -> None:
        """
        Refresh the synchronous cache used by evaluate().

        Called by the harness before starting a run. This avoids making
        evaluate() async (which the Spec protocol does not support).
        """
        self._cached_total = total_records
        self._cached_class_mads = class_mads
        self._cached_class_count = class_counts

    # ------------------------------------------------------------------
    # Core evaluation (synchronous — called by Spec adapter)
    # ------------------------------------------------------------------

    def evaluate_sync(
        self,
        run_id: str,
        input_data: dict[str, Any],
        input_class: str,
        cluster_version: str | None,
        model_scores: dict[str, float],
        raw_outputs: dict[str, Any],
    ) -> dict:
        """
        Core logic. Returns a result dict consumed by the Spec adapter.

        Always returns regime and mad. If drift is detected, appends a
        DriftSignal to _pending_signals. If convergent, appends a
        ConvergenceRecord to _pending_records.

        Returns
        -------
        {
          "regime":      "early" | "novel_class" | "convergent" | "drift",
          "mad":         float,
          "expected_mad": float | None,
          "drift_type":  str | None,
          "signal_id":   str | None,
          "message":     str,
        }
        """
        scores = list(model_scores.values())
        if not scores:
            return {
                "regime": "early",
                "mad": 0.0,
                "expected_mad": None,
                "drift_type": None,
                "signal_id": None,
                "message": "No model scores available yet",
            }

        observed_mad = _compute_mad(scores)

        # ── REGIME 1: Early ──────────────────────────────────────────
        if self._cached_total < self._config.min_baseline_size:
            record = self._make_record(
                run_id,
                input_data,
                input_class,
                cluster_version,
                model_scores,
                observed_mad,
                raw_outputs,
            )
            self._pending_records.append(record)
            return {
                "regime": "early",
                "mad": observed_mad,
                "expected_mad": None,
                "drift_type": None,
                "signal_id": None,
                "message": (
                    f"Baseline building: "
                    f"{self._cached_total}/{self._config.min_baseline_size} records"
                ),
            }

        expected_mad = self._cached_class_mads.get(input_class)
        class_count = self._cached_class_count.get(input_class, 0)

        # ── REGIME 2: Novel input class ───────────────────────────────
        if expected_mad is None or class_count < self._config.min_class_records:
            record = self._make_record(
                run_id,
                input_data,
                input_class,
                cluster_version,
                model_scores,
                observed_mad,
                raw_outputs,
            )
            self._pending_records.append(record)
            return {
                "regime": "novel_class",
                "mad": observed_mad,
                "expected_mad": None,
                "drift_type": None,
                "signal_id": None,
                "message": (
                    f"Novel class '{input_class}' "
                    f"({class_count}/{self._config.min_class_records} records). "
                    "Accumulating baseline data."
                ),
            }

        # ── REGIME 3: Mature — compare against baseline ────────────────
        threshold = expected_mad * self._config.drift_multiplier

        if observed_mad > threshold:
            drift_type, outlier = self._classify_drift(model_scores, scores)
            signal = DriftSignal(
                signal_id=str(uuid.uuid4()),
                run_id=run_id,
                timestamp=datetime.now(timezone.utc),
                drift_type=drift_type,
                input_fingerprint=_fingerprint(input_data),
                input_class=input_class,
                model_scores=model_scores,
                observed_mad=observed_mad,
                expected_mad=expected_mad,
                baseline_records=class_count,
                outlier_model=outlier,
                implicated_specs=list(self._spec_versions.keys()),
                representative_fps=[],  # filled by harness from baseline store
            )
            self._pending_signals.append(signal)
            return {
                "regime": "drift",
                "mad": observed_mad,
                "expected_mad": expected_mad,
                "drift_type": drift_type.value,
                "signal_id": signal.signal_id,
                "message": (
                    f"Drift detected: MAD {observed_mad:.3f} "
                    f"> threshold {threshold:.3f} "
                    f"(expected {expected_mad:.3f} × {self._config.drift_multiplier}). "
                    f"Type: {drift_type.value}."
                ),
            }

        # Convergent — append to baseline
        record = self._make_record(
            run_id,
            input_data,
            input_class,
            cluster_version,
            model_scores,
            observed_mad,
            raw_outputs,
        )
        self._pending_records.append(record)
        return {
            "regime": "convergent",
            "mad": observed_mad,
            "expected_mad": expected_mad,
            "drift_type": None,
            "signal_id": None,
            "message": (f"Convergent: MAD {observed_mad:.3f} " f"≤ threshold {threshold:.3f}"),
        }

    # ------------------------------------------------------------------
    # Drain queues (called by harness after orchestrator.run())
    # ------------------------------------------------------------------

    def drain_signals(self) -> list[DriftSignal]:
        """Return and clear all pending drift signals."""
        out = list(self._pending_signals)
        self._pending_signals.clear()
        return out

    def drain_records(self) -> list[ConvergenceRecord]:
        """Return and clear all pending convergence records."""
        out = list(self._pending_records)
        self._pending_records.clear()
        return out

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _make_record(
        self,
        run_id: str,
        input_data: dict[str, Any],
        input_class: str,
        cluster_version: str | None,
        model_scores: dict[str, float],
        mad: float,
        raw_outputs: dict[str, Any],
    ) -> ConvergenceRecord:
        import statistics as _st

        scores = list(model_scores.values())
        consensus = _st.median(scores)
        confidence = max(0.0, 1.0 - mad)
        return ConvergenceRecord(
            run_id=run_id,
            timestamp=datetime.now(timezone.utc),
            input_fingerprint=_fingerprint(input_data),
            input_class=input_class,
            cluster_version=cluster_version,
            model_scores=model_scores,
            consensus_score=consensus,
            inter_model_mad=mad,
            confidence=confidence,
            spec_versions=dict(self._spec_versions),
            raw_outputs=raw_outputs,
        )

    def _classify_drift(
        self,
        model_scores: dict[str, float],
        scores: list[float],
    ) -> tuple[DriftType, str | None]:
        """
        Determine drift type from the score distribution.

        MODEL_OUTLIER: one model is > outlier_threshold σ from the others.
        CRITERIA_GAP:  all models disagree roughly equally.
        """
        if len(scores) < 2:
            return DriftType.UNKNOWN, None

        for model_id, score in model_scores.items():
            others = [s for m, s in model_scores.items() if m != model_id]
            if not others:
                continue
            others_mean = statistics.mean(others)
            others_std = statistics.stdev(others) if len(others) > 1 else 0.0
            if (
                others_std > 0
                and abs(score - others_mean) / others_std > self._config.outlier_threshold
            ):
                return DriftType.MODEL_OUTLIER, model_id

        return DriftType.CRITERIA_GAP, None


# ---------------------------------------------------------------------------
# Spec adapter (requires manifold to be installed)
# ---------------------------------------------------------------------------


def make_convergence_spec(monitor: ConvergenceMonitor) -> Any:
    """
    Wrap a ConvergenceMonitor in a Manifold Spec.

    Lazily imports manifold.core.spec so that models.py / stores.py /
    events.py remain usable without manifold installed (e.g. in tests).

    The Spec reads model_scores, input_class, and input_data from the
    context data dict. These keys must be populated by the workflow's
    consensus step before the invariant runs.

    Usage
    -----
        monitor = ConvergenceMonitor(baseline_store, config)
        spec = make_convergence_spec(monitor)
        orchestrator = OrchestratorBuilder().with_spec(spec).build()
    """
    try:
        from manifold.core.spec import Spec, SpecResult
        from manifold.core.context import Context
    except ImportError as e:
        raise ImportError(
            "manifold must be installed to use make_convergence_spec(). "
            "Install with: pip install manifold-ai"
        ) from e

    class ConvergenceMonitorSpec(Spec):
        """
        Invariant spec that wraps a ConvergenceMonitor.

        Always returns SpecResult.ok() — drift does not fail the workflow.
        Drift information is in result.data and drained by the harness
        via monitor.drain_signals() after each run.
        """

        rule_id = "convergence_monitor"

        @property
        def tags(self) -> tuple[str, ...]:
            return ("invariant", "convergence", "hmmv")

        def evaluate(self, context: Context, candidate=None) -> SpecResult:
            cfg = monitor._config
            scores = context.get_data(cfg.record_mad_field)
            cls = context.get_data(cfg.record_class_field, "unknown")
            raw_in = context.get_data(cfg.record_input_field, {})
            raw_out = context.get_data(cfg.record_output_field, {})
            c_ver = context.get_data("cluster_version")

            if not scores:
                return SpecResult.ok(
                    rule_id=self.rule_id,
                    message="No model scores in context — skipping convergence check",
                    tags=self.tags,
                    data={"regime": "waiting"},
                )

            result = monitor.evaluate_sync(
                run_id=context.run_id,
                input_data=raw_in if isinstance(raw_in, dict) else {"value": raw_in},
                input_class=cls,
                cluster_version=c_ver,
                model_scores=scores,
                raw_outputs=raw_out if isinstance(raw_out, dict) else {},
            )

            return SpecResult.ok(
                rule_id=self.rule_id,
                message=result["message"],
                tags=self.tags,
                data=result,
            )

    return ConvergenceMonitorSpec()
