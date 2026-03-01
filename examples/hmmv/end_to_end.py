"""
examples/hmmv/end_to_end.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Full worked example: from setup to proposal approval.

This file is self-contained and runnable:
    python3 -m examples.hmmv.end_to_end

It demonstrates:
  1. Harness setup with in-memory stores
  2. Early regime: 22 runs with converging models → baseline building
  3. Mature regime: normal convergent runs (quiet)
  4. Drift trigger: edge case input splits models
  5. CorrectionRunner: full pipeline with stub LLM + stub model runner
  6. Proposal review: inspect → approve → spec registry updated
  7. Verification: re-run drifting input → regime returns to convergent

No real LLM or model calls are made. All external dependencies are stubs
that simulate realistic behaviour (converging scores for normal inputs,
divergent scores for the one edge-case input).
"""

from __future__ import annotations

import asyncio
import json
import logging
import statistics
import uuid
from dataclasses import replace
from datetime import datetime, timezone

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)-8s %(name)s: %(message)s",
)
log = logging.getLogger("example")

from manifold.testing.convergence import ConvergenceConfig, ConvergenceMonitor
from manifold.testing.correction import CorrectionRunner
from manifold.testing.models import (
    DriftSignal, DriftType, ProposalStatus, ReviewStatus, SpecProposal,
    _compute_mad,
)
from manifold.testing.stores import (
    InMemoryBaselineStore,
    InMemoryProposalStore,
    InMemorySnapshotStore,
    InMemorySpecRegistry,
)


# =============================================================================
# STUB: Model stubs simulating 4 diverse LLM models
# =============================================================================

EDGE_CASE_INPUT = {
    "name": "Caritas Berlin e.V.",
    "description": "Catholic welfare organisation providing social services.",
    "funding_tags": ["soziale_arbeit", "wohlfahrt"],
}

# Normal inputs → all 4 models within ~0.05 of each other
NORMAL_SCORES = {
    "gpt-4o":        0.82,
    "gemini-flash":  0.80,
    "llama-3.3":     0.81,
    "mistral-small": 0.79,
}

# Edge case → models split: 2 say strongly religious, 2 say secular welfare
EDGE_CASE_SCORES_BEFORE = {
    "gpt-4o":        0.85,
    "gemini-flash":  0.85,
    "llama-3.3":    -0.60,
    "mistral-small": -0.65,
}

# After proposed criteria applied → all models converge
EDGE_CASE_SCORES_AFTER = {
    "gpt-4o":        0.80,
    "gemini-flash":  0.79,
    "llama-3.3":     0.78,
    "mistral-small": 0.77,
}


async def stub_model_runner(
    input_data: dict,
    criteria_hint: str,
    model_id: str,
) -> float:
    """
    Stub model runner used by CorrectionRunner during validation.

    If criteria_hint is non-empty (correction workflow) AND the input
    matches the edge case → return converged scores.
    Otherwise → return the before-correction edge case scores.
    """
    is_edge_case = "caritas" in input_data.get("name", "").lower()
    has_criteria = bool(criteria_hint.strip())

    if is_edge_case and has_criteria:
        return EDGE_CASE_SCORES_AFTER[model_id]
    elif is_edge_case:
        return EDGE_CASE_SCORES_BEFORE[model_id]
    else:
        return NORMAL_SCORES.get(model_id, 0.80)


async def stub_llm_caller(prompt: str) -> str:
    """Stub LLM that returns a canned correction proposal."""
    return json.dumps({
        "proposed_change": (
            "Add explicit criterion for Catholic/Protestant welfare organisations: "
            "organisations whose primary mission is social welfare but are operated "
            "by a religious body should be classified as ngo_religious. "
            "The religious character of the operating body takes precedence over "
            "the service domain."
        ),
        "proposed_spec_code": (
            "# Criterion: welfare org operated by religious body → ngo_religious\n"
            "RELIGIOUS_WELFARE_KEYWORDS = ['caritas', 'diakonie', 'malteser',\n"
            "                               'johanniter', 'rotes kreuz']\n"
            "org_name_lower = candidate.get('name', '').lower()\n"
            "if any(kw in org_name_lower for kw in RELIGIOUS_WELFARE_KEYWORDS):\n"
            "    return SpecResult.ok(rule_id=self.rule_id,\n"
            "                        message='Religious welfare org: ngo_religious',\n"
            "                        data={'religious_welfare': True})"
        ),
        "hypothesis": (
            "Catholic welfare orgs like Caritas are operated by the Catholic Church "
            "and should be classified as ngo_religious regardless of their service domain. "
            "Explicit keyword matching for well-known religious welfare bodies removes "
            "the ambiguity that causes model divergence."
        ),
        "target_spec_id": "classify_spec_v1",
    })


# =============================================================================
# Lightweight harness (direct wiring — no external manifold dependency)
# =============================================================================

MODEL_IDS = ["gpt-4o", "gemini-flash", "llama-3.3", "mistral-small"]


class DirectHarness:
    """
    Minimal harness for the example.
    Directly wires ConvergenceMonitor + CorrectionRunner + stores.
    In production, use HMMVTestHarness which wraps all of this.
    """

    def __init__(self):
        self.baseline      = InMemoryBaselineStore()
        self.snapshots     = InMemorySnapshotStore()
        self.proposals     = InMemoryProposalStore()
        self.spec_registry = InMemorySpecRegistry()

        self.config  = ConvergenceConfig(
            min_baseline_size=20,
            drift_multiplier=2.5,
            min_class_records=5,
        )
        self.monitor = ConvergenceMonitor(
            baseline_store=self.baseline,
            config=self.config,
            spec_versions={"classify_spec_v1": "1.0.0"},
        )
        self.correction_runner = CorrectionRunner(
            llm_caller=stub_llm_caller,
            model_runner=stub_model_runner,
            model_ids=MODEL_IDS,
            improvement_threshold=0.25,
        )

        self.total_runs: int = 0
        self.drift_signals: list[DriftSignal] = []
        self.proposals_generated: list[SpecProposal] = []

    async def _refresh_cache(self):
        total    = await self.baseline.total_records()
        snapshot = await self.snapshots.latest()
        if snapshot and snapshot.total_records > 0:
            mads   = snapshot.mad_by_class
            counts = snapshot.records_by_class
        else:
            mads, counts = {}, {}
            for r in self.baseline._records:
                counts[r.input_class] = counts.get(r.input_class, 0) + 1
            by_class: dict[str, list] = {}
            for r in self.baseline._records:
                by_class.setdefault(r.input_class, []).append(r.inter_model_mad)
            mads = {c: statistics.mean(vs) for c, vs in by_class.items()}
        self.monitor.update_baseline_cache(total, mads, counts)

    async def run(
        self,
        input_data: dict,
        model_scores: dict[str, float],
        input_class: str = "ngo_religious",
    ) -> dict:
        """Simulate a single workflow run and return convergence result."""
        self.total_runs += 1
        run_id = str(uuid.uuid4())
        await self._refresh_cache()

        result = self.monitor.evaluate_sync(
            run_id=run_id,
            input_data=input_data,
            input_class=input_class,
            cluster_version="v1",
            model_scores=model_scores,
            raw_outputs={},
        )

        signals = self.monitor.drain_signals()
        records = self.monitor.drain_records()

        for r in records:
            await self.baseline.append(r)

        for sig in signals:
            sig = replace(sig, triggering_input=input_data)
            await self.baseline.append_signal(sig)
            self.drift_signals.append(sig)
            log.info("DRIFT DETECTED: %s on class=%s MAD %.3f (expected %.3f)",
                     sig.drift_type.value, sig.input_class,
                     sig.observed_mad, sig.expected_mad or 0)

            log.info("Starting correction workflow for signal %s ...", sig.signal_id[:8])
            proposal = await self.correction_runner.run(sig)
            if proposal:
                await self.proposals.write(proposal)
                self.proposals_generated.append(proposal)
                log.info("Proposal ready: %s status=%s improvement=%.4f",
                         proposal.proposal_id[:8],
                         proposal.proposal_status.value,
                         proposal.mad_improvement or 0.0)

        total = await self.baseline.total_records()
        if total > 0 and total % 10 == 0:
            snapshot = await self.baseline.take_snapshot(self.spec_registry)
            await self.snapshots.write(snapshot)

        return {
            "run_id":    run_id,
            "regime":    result["regime"],
            "mad":       result["mad"],
            "message":   result["message"],
            "had_drift": len(signals) > 0,
        }


# =============================================================================
# Main example flow
# =============================================================================

async def main():
    harness = DirectHarness()

    print("\n" + "═" * 70)
    print("MANIFOLD TESTING — End-to-End Example")
    print("═" * 70)

    # ─────────────────────────────────────────────────────────────────────────
    print("\n[1] EARLY REGIME — Building baseline (20 runs needed)")
    print("─" * 50)

    for i in range(22):
        org = {"name": f"Test NGO {i}", "funding": 10_000 + i * 500}
        scores = {m: NORMAL_SCORES[m] + (i % 3 - 1) * 0.01 for m in MODEL_IDS}
        r = await harness.run(org, scores)
        if (i + 1) % 5 == 0:
            print(f"  Run {i+1:2d}: regime={r['regime']:<12} MAD={r['mad']:.4f}  {r['message'][:60]}")

    baseline_size = await harness.baseline.total_records()
    print(f"\n  Baseline built: {baseline_size} records")
    assert baseline_size >= 20, "Should have crossed min_baseline_size"
    assert harness.drift_signals == [], "No drift expected during baseline building"
    print("  No drift signals during baseline phase — as expected.")

    # ─────────────────────────────────────────────────────────────────────────
    print("\n[2] MATURE REGIME — Normal convergent runs")
    print("─" * 50)

    for i in range(5):
        org = {"name": f"Normal NGO {i}", "funding": 50_000}
        r = await harness.run(org, NORMAL_SCORES)
        print(f"  Run {i+1}: regime={r['regime']:<12} MAD={r['mad']:.4f}")

    print("  All runs convergent — drift detection active but quiet.")

    # ─────────────────────────────────────────────────────────────────────────
    print("\n[3] DRIFT TRIGGER — Edge case input")
    print("─" * 50)
    print(f"  Input: {EDGE_CASE_INPUT['name']}")
    print(f"  Scores: gpt={EDGE_CASE_SCORES_BEFORE['gpt-4o']:.2f}  "
          f"gemini={EDGE_CASE_SCORES_BEFORE['gemini-flash']:.2f}  "
          f"llama={EDGE_CASE_SCORES_BEFORE['llama-3.3']:.2f}  "
          f"mistral={EDGE_CASE_SCORES_BEFORE['mistral-small']:.2f}")
    print(f"  Expected MAD: ~{_compute_mad(list(EDGE_CASE_SCORES_BEFORE.values())):.3f}")

    r = await harness.run(EDGE_CASE_INPUT, EDGE_CASE_SCORES_BEFORE)
    print(f"\n  Result: regime={r['regime']}  MAD={r['mad']:.4f}")
    print(f"  Message: {r['message']}")

    assert r["regime"] == "drift", f"Expected drift, got {r['regime']}"
    assert len(harness.drift_signals) == 1

    # ─────────────────────────────────────────────────────────────────────────
    print("\n[4] CORRECTION WORKFLOW OUTPUT")
    print("─" * 50)

    proposals = await harness.proposals.pending_proposals()
    assert len(proposals) == 1, f"Expected 1 proposal, got {len(proposals)}"
    proposal = proposals[0]

    print(f"  Proposal ID:      {proposal.proposal_id[:16]}...")
    print(f"  Status:           {proposal.proposal_status.value}")
    print(f"  Target spec:      {proposal.target_spec_id}")
    print(f"  MAD before:       {proposal.validation_mad_before:.4f}")
    print(f"  MAD after:        {proposal.validation_mad_after:.4f}")
    print(f"  Improvement:      {proposal.mad_improvement:.4f} "
          f"({proposal.mad_improvement / proposal.validation_mad_before * 100:.1f}%)")
    print(f"\n  Hypothesis:\n    {proposal.hypothesis}")

    assert proposal.proposal_status == ProposalStatus.VALIDATED
    assert proposal.mad_improvement > 0

    # ─────────────────────────────────────────────────────────────────────────
    print("\n[5] HUMAN REVIEW — Approve proposal")
    print("─" * 50)

    approved = replace(
        proposal,
        review_status=ReviewStatus.APPROVED,
        reviewer_notes="Confirmed: Caritas-type orgs should be ngo_religious. Approved.",
        applied_at=datetime.now(timezone.utc),
    )
    await harness.spec_registry.apply_proposal(approved)

    new_versions = await harness.spec_registry.current_versions()
    print("  Approved. Spec registry updated:")
    for spec_id, version in new_versions.items():
        print(f"    {spec_id}: {version}")

    # ─────────────────────────────────────────────────────────────────────────
    print("\n[6] VERIFICATION — Re-run edge case with updated model behaviour")
    print("─" * 50)
    print("  (Models now return converged scores for Caritas-type inputs)")

    initial_signal_count = len(harness.drift_signals)
    r2 = await harness.run(EDGE_CASE_INPUT, EDGE_CASE_SCORES_AFTER)
    print(f"\n  Result: regime={r2['regime']}  MAD={r2['mad']:.4f}")
    print(f"  Message: {r2['message']}")

    assert r2["regime"] in ("convergent", "novel_class"), \
        f"Expected convergent after fix, got {r2['regime']}"
    assert len(harness.drift_signals) == initial_signal_count, "No new drift after fix"
    print("  No new drift signal — edge case now classified consistently.")

    # ─────────────────────────────────────────────────────────────────────────
    print("\n" + "═" * 70)
    print("SUMMARY")
    print("═" * 70)
    print(f"  Total runs executed:      {harness.total_runs}")
    print(f"  Baseline records built:   {await harness.baseline.total_records()}")
    print(f"  Drift signals detected:   {len(harness.drift_signals)}")
    print(f"  Proposals generated:      {len(harness.proposals_generated)}")
    print(f"  Proposals validated:      "
          f"{sum(1 for p in harness.proposals_generated if p.proposal_status == ProposalStatus.VALIDATED)}")

    signal = harness.drift_signals[0]
    print(f"\n  Drift signal:")
    print(f"    Type:           {signal.drift_type.value}")
    print(f"    Input class:    {signal.input_class}")
    print(f"    Observed MAD:   {signal.observed_mad:.4f}")
    print(f"    Expected MAD:   {signal.expected_mad:.4f}")

    p = harness.proposals_generated[0]
    print(f"\n  Correction proposal:")
    print(f"    MAD reduction:  {p.mad_improvement:.4f} "
          f"({p.mad_improvement / p.validation_mad_before * 100:.1f}%)")
    print(f"    Validation:     {p.proposal_status.value}")
    print(f"    Models converged after: {p.models_converged_after}/{len(MODEL_IDS)}")

    print("\n  System operated correctly across all phases:")
    print("    early regime    → baseline accumulated, no false positives")
    print("    mature regime   → normal runs passed silently")
    print("    drift detected  → signal emitted, correction triggered")
    print("    correction run  → proposal generated and validated")
    print("    human reviewed  → spec registry updated")
    print("    re-verification → edge case now convergent")
    print()


if __name__ == "__main__":
    asyncio.run(main())
