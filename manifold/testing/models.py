"""
manifold.testing.models
~~~~~~~~~~~~~~~~~~~~~~~
Core data structures for adaptive convergence testing.

Design principles (consistent with manifold.core):
- All models are frozen dataclasses: immutable after creation
- All models have to_dict() for serialisation
- No business logic here — pure data, pure types
"""

from __future__ import annotations

import hashlib
import json
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class DriftType(Enum):
    """
    Classification of why convergence broke down.

    MODEL_OUTLIER   — one model diverges; others still agree.
                      The criteria are fine; that model may have changed.

    CRITERIA_GAP    — all models diverge from each other on a new input class.
                      The criteria don't cover this case yet.

    UNKNOWN         — insufficient data to classify. Treated conservatively:
                      correction workflow runs but proposes investigation,
                      not a spec change.

    Note: SILENT_CONSENSUS (all agree but wrong) is explicitly out of scope.
    It requires a human baseline layer and cannot be detected automatically.
    """
    MODEL_OUTLIER = "model_outlier"
    CRITERIA_GAP  = "criteria_gap"
    UNKNOWN       = "unknown"


class ProposalStatus(Enum):
    PENDING   = "pending"
    VALIDATED = "validated"   # technically validated via re-run
    REJECTED  = "rejected"    # validation showed no improvement


class ReviewStatus(Enum):
    PENDING  = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    MODIFIED = "modified"     # human modified before approving


# ---------------------------------------------------------------------------
# ConvergenceRecord — the atom of the baseline
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ConvergenceRecord:
    """
    A single run that achieved acceptable convergence.

    These records accumulate in the BaselineStore and define
    what "normal" looks like for each input class. Drift detection
    compares live observations against this history.

    Fields
    ------
    run_id          : globally unique run identifier
    timestamp       : UTC time of the run
    input_fingerprint : sha256 of canonical input (not raw input — privacy)
    input_class     : cluster label (assigned by clustering agent, may be
                      provisional until cluster model stabilises)
    cluster_version : version tag of the clustering model that assigned the
                      label. Records with different cluster versions may not
                      be directly comparable — used to detect when re-clustering
                      is needed.
    model_scores    : {model_id: score} — numeric output per model
    consensus_score : agreed-upon value (e.g. median across models)
    inter_model_mad : mean absolute deviation across model_scores
    confidence      : derived confidence (1 - normalised MAD); range [0, 1]
    spec_versions   : {spec_id: version} at time of run — for changelog
    raw_outputs     : {model_id: raw output dict} — full detail for debugging
    """
    run_id:            str
    timestamp:         datetime
    input_fingerprint: str
    input_class:       str                       # cluster label
    cluster_version:   str | None                # None = pre-stable cluster
    model_scores:      dict[str, float]          # model_id → score
    consensus_score:   float
    inter_model_mad:   float
    confidence:        float                     # [0, 1]
    spec_versions:     dict[str, str]            # spec_id → version
    raw_outputs:       dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Constructors
    # ------------------------------------------------------------------

    @classmethod
    def create(
        cls,
        run_id: str,
        input_data: dict[str, Any],
        input_class: str,
        cluster_version: str | None,
        model_scores: dict[str, float],
        spec_versions: dict[str, str],
        raw_outputs: dict[str, Any] | None = None,
    ) -> "ConvergenceRecord":
        """
        Factory that computes derived fields automatically.

        Args:
            run_id:          Unique run ID from orchestrator.
            input_data:      The raw input (used only for fingerprinting).
            input_class:     Cluster label assigned to this input.
            cluster_version: Version of the clustering model.
            model_scores:    {model_id: numeric_score}.
            spec_versions:   {spec_id: version_string}.
            raw_outputs:     Optional full outputs for debugging.
        """
        scores = list(model_scores.values())
        if not scores:
            raise ValueError("model_scores must not be empty")

        mad = _compute_mad(scores)
        consensus = statistics.median(scores)

        # Normalise MAD to [0, 1] using expected max range.
        # Scores are expected to be on [-1, 1] → max MAD = 1.0
        confidence = max(0.0, 1.0 - mad)

        fingerprint = _fingerprint(input_data)

        return cls(
            run_id=run_id,
            timestamp=datetime.now(timezone.utc),
            input_fingerprint=fingerprint,
            input_class=input_class,
            cluster_version=cluster_version,
            model_scores=model_scores,
            consensus_score=consensus,
            inter_model_mad=mad,
            confidence=confidence,
            spec_versions=spec_versions,
            raw_outputs=raw_outputs or {},
        )

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "run_id":            self.run_id,
            "timestamp":         self.timestamp.isoformat(),
            "input_fingerprint": self.input_fingerprint,
            "input_class":       self.input_class,
            "cluster_version":   self.cluster_version,
            "model_scores":      self.model_scores,
            "consensus_score":   self.consensus_score,
            "inter_model_mad":   self.inter_model_mad,
            "confidence":        self.confidence,
            "spec_versions":     self.spec_versions,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ConvergenceRecord":
        return cls(
            run_id=d["run_id"],
            timestamp=datetime.fromisoformat(d["timestamp"]),
            input_fingerprint=d["input_fingerprint"],
            input_class=d["input_class"],
            cluster_version=d.get("cluster_version"),
            model_scores=d["model_scores"],
            consensus_score=d["consensus_score"],
            inter_model_mad=d["inter_model_mad"],
            confidence=d["confidence"],
            spec_versions=d["spec_versions"],
            raw_outputs=d.get("raw_outputs", {}),
        )


# ---------------------------------------------------------------------------
# BaselineSnapshot — a point-in-time summary of the baseline
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BaselineSnapshot:
    """
    A versioned, point-in-time snapshot of the baseline statistics.

    The BaselineStore accumulates raw ConvergenceRecords (append-only,
    never modified). Periodically, when the baseline crosses a confidence
    threshold, a snapshot is taken and persisted separately.

    The system reads from the most recent valid snapshot during operation,
    not from raw records directly. This means the hot path is fast (small
    snapshot) while the full history is always available for analysis.

    Fields
    ------
    snapshot_id         : unique identifier for this snapshot
    created_at          : when it was taken
    total_records       : total convergence records at snapshot time
    records_by_class    : {input_class: count}
    mad_by_class        : {input_class: mean MAD across records}
    mad_stddev_by_class : {input_class: std deviation of MAD}
    confidence_by_class : {input_class: mean confidence}
    spec_versions       : spec versions active when snapshot was taken
    proposals_since_last: list of SpecProposal IDs applied since previous snapshot
    cluster_version     : clustering model version used for records in snapshot
    is_valid            : False if a spec change invalidated some records
    notes               : free-text (e.g. why snapshot was triggered)
    """
    snapshot_id:          str
    created_at:           datetime
    total_records:        int
    records_by_class:     dict[str, int]
    mad_by_class:         dict[str, float]
    mad_stddev_by_class:  dict[str, float]
    confidence_by_class:  dict[str, float]
    spec_versions:        dict[str, str]
    proposals_since_last: list[str]               # SpecProposal IDs
    cluster_version:      str | None
    is_valid:             bool = True
    notes:                str = ""

    def to_dict(self) -> dict:
        return {
            "snapshot_id":          self.snapshot_id,
            "created_at":           self.created_at.isoformat(),
            "total_records":        self.total_records,
            "records_by_class":     self.records_by_class,
            "mad_by_class":         self.mad_by_class,
            "mad_stddev_by_class":  self.mad_stddev_by_class,
            "confidence_by_class":  self.confidence_by_class,
            "spec_versions":        self.spec_versions,
            "proposals_since_last": self.proposals_since_last,
            "cluster_version":      self.cluster_version,
            "is_valid":             self.is_valid,
            "notes":                self.notes,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "BaselineSnapshot":
        return cls(
            snapshot_id=d["snapshot_id"],
            created_at=datetime.fromisoformat(d["created_at"]),
            total_records=d["total_records"],
            records_by_class=d["records_by_class"],
            mad_by_class=d["mad_by_class"],
            mad_stddev_by_class=d["mad_stddev_by_class"],
            confidence_by_class=d["confidence_by_class"],
            spec_versions=d["spec_versions"],
            proposals_since_last=d["proposals_since_last"],
            cluster_version=d.get("cluster_version"),
            is_valid=d.get("is_valid", True),
            notes=d.get("notes", ""),
        )


# ---------------------------------------------------------------------------
# DriftSignal — emitted when convergence breaks down
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DriftSignal:
    """
    Emitted by the ConvergenceMonitor spec when inter-model agreement
    exceeds the drift threshold.

    Stored as an artifact on the context, then consumed by the
    EventConsumer which triggers the correction workflow.

    Drift does NOT fail the primary workflow.
    The primary output (consensus_score) is still valid and used.
    Drift is a signal to investigate criteria, not a production failure.

    Fields
    ------
    signal_id           : unique identifier
    run_id              : the run that triggered this signal
    timestamp           : UTC
    drift_type          : MODEL_OUTLIER | CRITERIA_GAP | UNKNOWN
    input_fingerprint   : fingerprint of the triggering input
    input_class         : cluster label of the triggering input
    model_scores        : what each model produced
    observed_mad        : MAD observed in this run
    expected_mad        : historical baseline MAD for this class (None = new class)
    baseline_records    : how many baseline records exist for this class
    outlier_model       : model_id if drift_type == MODEL_OUTLIER, else None
    implicated_specs    : spec rule_ids that were evaluating when drift occurred
    representative_fps  : fingerprints of other inputs from same class that converged
                          (context for correction workflow)
    """
    signal_id:           str
    run_id:              str
    timestamp:           datetime
    drift_type:          DriftType
    input_fingerprint:   str
    input_class:         str
    model_scores:        dict[str, float]
    observed_mad:        float
    expected_mad:        float | None
    baseline_records:    int
    outlier_model:       str | None
    implicated_specs:    list[str]
    representative_fps:  list[str]               # fingerprints for correction context
    triggering_input:    dict = field(default_factory=dict)
    # Raw input that triggered drift — populated by harness, used by CorrectionRunner
    # for re-running models during hypothesis validation.

    def to_dict(self) -> dict:
        return {
            "signal_id":          self.signal_id,
            "run_id":             self.run_id,
            "timestamp":          self.timestamp.isoformat(),
            "drift_type":         self.drift_type.value,
            "input_fingerprint":  self.input_fingerprint,
            "input_class":        self.input_class,
            "model_scores":       self.model_scores,
            "observed_mad":       self.observed_mad,
            "expected_mad":       self.expected_mad,
            "baseline_records":   self.baseline_records,
            "outlier_model":      self.outlier_model,
            "implicated_specs":   self.implicated_specs,
            "representative_fps": self.representative_fps,
            "triggering_input":   self.triggering_input,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "DriftSignal":
        return cls(
            signal_id=d["signal_id"],
            run_id=d["run_id"],
            timestamp=datetime.fromisoformat(d["timestamp"]),
            drift_type=DriftType(d["drift_type"]),
            input_fingerprint=d["input_fingerprint"],
            input_class=d["input_class"],
            model_scores=d["model_scores"],
            observed_mad=d["observed_mad"],
            expected_mad=d.get("expected_mad"),
            baseline_records=d["baseline_records"],
            outlier_model=d.get("outlier_model"),
            implicated_specs=d.get("implicated_specs", []),
            representative_fps=d.get("representative_fps", []),
            triggering_input=d.get("triggering_input", {}),
        )


# ---------------------------------------------------------------------------
# SpecProposal — output of the correction workflow
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SpecProposal:
    """
    A proposed spec change, produced by the correction workflow.

    Never applied automatically. Requires:
    1. Technical validation: re-run drifting inputs with proposed spec,
       confirm MAD improves (done by correction workflow itself).
    2. Human review: semantic correctness cannot be automated.

    The proposal is an immutable record of the entire decision chain:
    what triggered it, what was proposed, and what the evidence was.

    Fields
    ------
    proposal_id           : unique identifier
    created_at            : UTC
    triggered_by          : DriftSignal that started the correction workflow
    target_spec_id        : which spec is being changed
    current_spec_version  : version before change
    proposed_change       : human-readable description of the change
    proposed_spec_code    : the actual Python implementation (as string)
    hypothesis            : why this change should restore convergence
    drift_examples        : input fingerprints that triggered drift
    convergence_examples  : input fingerprints that still converged (controls)
    proposal_status       : pending | validated | rejected
    validation_mad_before : MAD on drift examples under current spec
    validation_mad_after  : MAD on drift examples under proposed spec
    models_converged_after: how many models agreed under proposed spec
    review_status         : pending | approved | rejected | modified
    reviewer_notes        : free-text from human reviewer
    applied_at            : UTC when applied to registry (None until applied)
    """
    proposal_id:            str
    created_at:             datetime
    triggered_by_signal_id: str                  # FK to DriftSignal
    target_spec_id:         str
    current_spec_version:   str
    proposed_change:        str
    proposed_spec_code:     str
    hypothesis:             str
    drift_examples:         list[str]            # input fingerprints
    convergence_examples:   list[str]            # input fingerprints
    proposal_status:        ProposalStatus       = ProposalStatus.PENDING
    validation_mad_before:  float | None         = None
    validation_mad_after:   float | None         = None
    models_converged_after: int | None           = None
    review_status:          ReviewStatus         = ReviewStatus.PENDING
    reviewer_notes:         str | None           = None
    applied_at:             datetime | None      = None

    @property
    def mad_improvement(self) -> float | None:
        """Absolute MAD reduction. Positive = improvement."""
        if self.validation_mad_before is None or self.validation_mad_after is None:
            return None
        return self.validation_mad_before - self.validation_mad_after

    def to_dict(self) -> dict:
        return {
            "proposal_id":            self.proposal_id,
            "created_at":             self.created_at.isoformat(),
            "triggered_by_signal_id": self.triggered_by_signal_id,
            "target_spec_id":         self.target_spec_id,
            "current_spec_version":   self.current_spec_version,
            "proposed_change":        self.proposed_change,
            "proposed_spec_code":     self.proposed_spec_code,
            "hypothesis":             self.hypothesis,
            "drift_examples":         self.drift_examples,
            "convergence_examples":   self.convergence_examples,
            "proposal_status":        self.proposal_status.value,
            "validation_mad_before":  self.validation_mad_before,
            "validation_mad_after":   self.validation_mad_after,
            "models_converged_after": self.models_converged_after,
            "review_status":          self.review_status.value,
            "reviewer_notes":         self.reviewer_notes,
            "applied_at":             self.applied_at.isoformat() if self.applied_at else None,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SpecProposal":
        return cls(
            proposal_id=d["proposal_id"],
            created_at=datetime.fromisoformat(d["created_at"]),
            triggered_by_signal_id=d["triggered_by_signal_id"],
            target_spec_id=d["target_spec_id"],
            current_spec_version=d["current_spec_version"],
            proposed_change=d["proposed_change"],
            proposed_spec_code=d["proposed_spec_code"],
            hypothesis=d["hypothesis"],
            drift_examples=d["drift_examples"],
            convergence_examples=d["convergence_examples"],
            proposal_status=ProposalStatus(d["proposal_status"]),
            validation_mad_before=d.get("validation_mad_before"),
            validation_mad_after=d.get("validation_mad_after"),
            models_converged_after=d.get("models_converged_after"),
            review_status=ReviewStatus(d.get("review_status", "pending")),
            reviewer_notes=d.get("reviewer_notes"),
            applied_at=datetime.fromisoformat(d["applied_at"]) if d.get("applied_at") else None,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _compute_mad(values: list[float]) -> float:
    """Mean absolute deviation from the mean."""
    if not values:
        return 0.0
    mean = statistics.mean(values)
    return statistics.mean(abs(v - mean) for v in values)


def _fingerprint(data: dict[str, Any]) -> str:
    """Stable sha256 fingerprint of canonical input data."""
    serialised = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(serialised.encode()).hexdigest()[:16]
