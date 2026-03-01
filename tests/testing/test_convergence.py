"""
Tests for manifold.testing.convergence

ConvergenceMonitor is tested standalone (no manifold dependency).
We verify:
- All three regimes behave correctly
- Drift classification (MODEL_OUTLIER vs CRITERIA_GAP)
- Signal/record queues are properly drained
- Cache update affects behaviour
- Idempotency: multiple drains are safe
"""

from __future__ import annotations

import uuid
from datetime import timezone

import pytest

from manifold.testing.convergence import ConvergenceConfig, ConvergenceMonitor
from manifold.testing.models import DriftType
from manifold.testing.stores import InMemoryBaselineStore

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def make_monitor(
    min_baseline_size: int = 10,
    drift_multiplier: float = 2.5,
    outlier_threshold: float = 2.0,
    min_class_records: int = 3,
) -> ConvergenceMonitor:
    store = InMemoryBaselineStore()
    config = ConvergenceConfig(
        min_baseline_size=min_baseline_size,
        drift_multiplier=drift_multiplier,
        outlier_threshold=outlier_threshold,
        min_class_records=min_class_records,
    )
    return ConvergenceMonitor(store, config)


def run_eval(
    monitor: ConvergenceMonitor,
    model_scores: dict[str, float],
    input_class: str = "ngo_religious",
    run_id: str | None = None,
) -> dict:
    return monitor.evaluate_sync(
        run_id=run_id or str(uuid.uuid4()),
        input_data={"name": "Test Org"},
        input_class=input_class,
        cluster_version="v1",
        model_scores=model_scores,
        raw_outputs={},
    )


CONVERGED_SCORES = {"a": 0.80, "b": 0.78, "c": 0.82, "d": 0.79}
# Two-camp split: a+b agree, c+d disagree → high MAD, no single outlier → CRITERIA_GAP
DIVERGED_SCORES = {"a": 0.80, "b": 0.80, "c": -0.80, "d": -0.80}
# One model far from the other three → MODEL_OUTLIER
OUTLIER_SCORES = {"a": 0.80, "b": 0.78, "c": 0.82, "d": -0.90}


# ---------------------------------------------------------------------------
# Regime 1: Early
# ---------------------------------------------------------------------------


class TestEarlyRegime:
    def test_regime_is_early_below_baseline_threshold(self):
        m = make_monitor(min_baseline_size=100)
        m.update_baseline_cache(total_records=5, class_mads={}, class_counts={})
        result = run_eval(m, CONVERGED_SCORES)
        assert result["regime"] == "early"

    def test_no_signal_emitted_in_early_regime(self):
        m = make_monitor(min_baseline_size=100)
        m.update_baseline_cache(5, {}, {})
        run_eval(m, DIVERGED_SCORES)  # even diverged — no signal in early regime
        assert m.drain_signals() == []

    def test_record_always_added_in_early_regime(self):
        m = make_monitor(min_baseline_size=100)
        m.update_baseline_cache(5, {}, {})
        run_eval(m, CONVERGED_SCORES)
        records = m.drain_records()
        assert len(records) == 1
        assert records[0].input_class == "ngo_religious"

    def test_early_message_contains_progress(self):
        m = make_monitor(min_baseline_size=50)
        m.update_baseline_cache(12, {}, {})
        result = run_eval(m, CONVERGED_SCORES)
        assert "12/50" in result["message"]


# ---------------------------------------------------------------------------
# Regime 2: Novel input class
# ---------------------------------------------------------------------------


class TestNovelClassRegime:
    def _mature_cache(self, monitor: ConvergenceMonitor, class_mads=None, class_counts=None):
        monitor.update_baseline_cache(
            total_records=500,
            class_mads=class_mads or {},
            class_counts=class_counts or {},
        )

    def test_novel_class_no_signal(self):
        m = make_monitor(min_baseline_size=10, min_class_records=5)
        self._mature_cache(m)
        run_eval(m, DIVERGED_SCORES, input_class="new_class")
        assert m.drain_signals() == []

    def test_novel_class_adds_record(self):
        m = make_monitor(min_baseline_size=10, min_class_records=5)
        self._mature_cache(m)
        run_eval(m, CONVERGED_SCORES, input_class="new_class")
        records = m.drain_records()
        assert len(records) == 1

    def test_known_class_below_min_records_treated_as_novel(self):
        m = make_monitor(min_baseline_size=10, min_class_records=5)
        self._mature_cache(m, class_mads={"cls": 0.04}, class_counts={"cls": 2})
        run_eval(m, DIVERGED_SCORES, input_class="cls")
        assert m.drain_signals() == []  # only 2 records, below min_class_records=5


# ---------------------------------------------------------------------------
# Regime 3: Mature / drift detection
# ---------------------------------------------------------------------------


class TestMatureRegime:
    def _setup_mature(self, monitor: ConvergenceMonitor, expected_mad=0.04, class_count=20):
        monitor.update_baseline_cache(
            total_records=500,
            class_mads={"ngo_religious": expected_mad},
            class_counts={"ngo_religious": class_count},
        )

    def test_convergent_run_no_signal(self):
        m = make_monitor(drift_multiplier=2.5)
        self._setup_mature(m, expected_mad=0.04)
        # MAD of CONVERGED_SCORES ≈ 0.014 — well below threshold 0.04 * 2.5 = 0.10
        result = run_eval(m, CONVERGED_SCORES)
        assert result["regime"] == "convergent"
        assert m.drain_signals() == []

    def test_convergent_run_adds_record(self):
        m = make_monitor(drift_multiplier=2.5)
        self._setup_mature(m, expected_mad=0.04)
        run_eval(m, CONVERGED_SCORES)
        assert len(m.drain_records()) == 1

    def test_diverged_run_emits_signal(self):
        m = make_monitor(drift_multiplier=2.5)
        self._setup_mature(m, expected_mad=0.04)
        # MAD of DIVERGED_SCORES ≈ 0.39 — well above threshold 0.10
        result = run_eval(m, DIVERGED_SCORES)
        assert result["regime"] == "drift"
        signals = m.drain_signals()
        assert len(signals) == 1

    def test_drift_signal_has_correct_run_id(self):
        m = make_monitor()
        self._setup_mature(m)
        run_id = str(uuid.uuid4())
        run_eval(m, DIVERGED_SCORES, run_id=run_id)
        signal = m.drain_signals()[0]
        assert signal.run_id == run_id

    def test_drift_signal_expected_mad_correct(self):
        m = make_monitor()
        self._setup_mature(m, expected_mad=0.04)
        run_eval(m, DIVERGED_SCORES)
        signal = m.drain_signals()[0]
        assert signal.expected_mad == pytest.approx(0.04)

    def test_drift_signal_has_timestamp(self):
        m = make_monitor()
        self._setup_mature(m)
        run_eval(m, DIVERGED_SCORES)
        signal = m.drain_signals()[0]
        assert signal.timestamp.tzinfo is not None  # timezone-aware

    def test_diverged_run_no_record_added(self):
        m = make_monitor()
        self._setup_mature(m)
        run_eval(m, DIVERGED_SCORES)
        m.drain_signals()
        assert m.drain_records() == []  # drifted run doesn't add to baseline


# ---------------------------------------------------------------------------
# Drift classification
# ---------------------------------------------------------------------------


class TestDriftClassification:
    def _setup(self) -> ConvergenceMonitor:
        m = make_monitor(drift_multiplier=2.0, outlier_threshold=2.0)
        m.update_baseline_cache(500, {"cls": 0.03}, {"cls": 20})
        return m

    def test_model_outlier_detected(self):
        m = self._setup()
        # Model 'd' is -0.90, others are ~0.80 — clear outlier
        run_eval(m, OUTLIER_SCORES, input_class="cls")
        signals = m.drain_signals()
        assert len(signals) == 1
        assert signals[0].drift_type == DriftType.MODEL_OUTLIER
        assert signals[0].outlier_model == "d"

    def test_criteria_gap_when_all_diverge(self):
        m = self._setup()
        run_eval(m, DIVERGED_SCORES, input_class="cls")
        signals = m.drain_signals()
        assert len(signals) == 1
        assert signals[0].drift_type == DriftType.CRITERIA_GAP
        assert signals[0].outlier_model is None

    def test_no_outlier_with_identical_scores(self):
        m = self._setup()
        # All the same — no drift expected
        scores = {"a": 0.8, "b": 0.8, "c": 0.8, "d": 0.8}
        run_eval(m, scores, input_class="cls")
        assert m.drain_signals() == []


# ---------------------------------------------------------------------------
# Queue drain behaviour
# ---------------------------------------------------------------------------


class TestDrainBehaviour:
    def test_drain_signals_empties_queue(self):
        m = make_monitor()
        m.update_baseline_cache(500, {"ngo_religious": 0.04}, {"ngo_religious": 20})
        run_eval(m, DIVERGED_SCORES)
        assert len(m.drain_signals()) == 1
        assert len(m.drain_signals()) == 0  # drained

    def test_drain_records_empties_queue(self):
        m = make_monitor(min_baseline_size=1)
        m.update_baseline_cache(500, {"ngo_religious": 0.04}, {"ngo_religious": 20})
        run_eval(m, CONVERGED_SCORES)
        assert len(m.drain_records()) == 1
        assert len(m.drain_records()) == 0

    def test_multiple_runs_accumulate(self):
        m = make_monitor(min_baseline_size=1)
        m.update_baseline_cache(500, {"ngo_religious": 0.04}, {"ngo_religious": 20})
        run_eval(m, CONVERGED_SCORES)
        run_eval(m, CONVERGED_SCORES)
        run_eval(m, CONVERGED_SCORES)
        assert len(m.drain_records()) == 3

    def test_no_scores_returns_early_gracefully(self):
        m = make_monitor()
        m.update_baseline_cache(500, {}, {})
        result = m.evaluate_sync(
            run_id="r1",
            input_data={},
            input_class="cls",
            cluster_version=None,
            model_scores={},  # empty
            raw_outputs={},
        )
        assert result["regime"] == "early"
        assert m.drain_signals() == []


# ---------------------------------------------------------------------------
# Cache update behaviour
# ---------------------------------------------------------------------------


class TestCacheUpdate:
    def test_updating_cache_changes_regime(self):
        m = make_monitor(min_baseline_size=50, min_class_records=3)

        # First: early regime
        m.update_baseline_cache(5, {}, {})
        r1 = run_eval(m, DIVERGED_SCORES)
        assert r1["regime"] == "early"
        m.drain_records()

        # Update cache to mature
        m.update_baseline_cache(500, {"ngo_religious": 0.04}, {"ngo_religious": 20})
        r2 = run_eval(m, DIVERGED_SCORES)
        assert r2["regime"] == "drift"

    def test_record_contains_correct_spec_versions(self):
        m = ConvergenceMonitor(
            InMemoryBaselineStore(),
            ConvergenceConfig(min_baseline_size=1),
            spec_versions={"classify_spec": "1.0.0", "threshold_spec": "2.1.0"},
        )
        m.update_baseline_cache(500, {"ngo_religious": 0.04}, {"ngo_religious": 20})
        run_eval(m, CONVERGED_SCORES)
        record = m.drain_records()[0]
        assert record.spec_versions["classify_spec"] == "1.0.0"
        assert record.spec_versions["threshold_spec"] == "2.1.0"

    def test_signal_timestamp_is_timezone_aware(self):
        m = make_monitor()
        m.update_baseline_cache(500, {"ngo_religious": 0.04}, {"ngo_religious": 20})
        run_eval(m, DIVERGED_SCORES)
        signal = m.drain_signals()[0]
        assert signal.timestamp.tzinfo == timezone.utc
