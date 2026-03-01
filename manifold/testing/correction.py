"""
manifold.testing.correction
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
CorrectionRunner — the real implementation of the correction workflow.

Replaces NoOpCorrectionRunner in harness.py once you wire up an LLM caller
and a ModelRunner (the two external dependencies).

Pipeline
--------
Given a DriftSignal, the CorrectionRunner executes four steps:

    1. analyze(signal) → CorrectionAnalysis
       Pure struct enrichment. No IO. Summarises what we know about the
       drift, identifies the probable root cause, decides which spec to target.

    2. generate_hypothesis(analysis) → Hypothesis
       LLM call. Produces a proposed_change description and proposed_spec_code.
       Behaviour differs by drift type:
         CRITERIA_GAP   → propose a spec addition/modification
         MODEL_OUTLIER  → recommend model audit (no spec change)
         UNKNOWN        → conservative: request investigation

    3. validate(hypothesis, signal) → ValidationResult
       Re-runs all models on the triggering input with the proposed criteria
       as additional context, measures MAD improvement.
       For MODEL_OUTLIER: validates by computing MAD excluding the outlier.

    4. assemble → SpecProposal
       Packages everything into an immutable SpecProposal for human review.

Protocols
---------
Two external dependencies are behind protocols so they can be stubbed in tests:

    LLMCaller   — async callable: (prompt: str) → str
                  Wire to any LLM provider (Anthropic, OpenAI, etc.)

    ModelRunner — async callable: (input_data: dict, criteria_hint: str,
                                   model_id: str) → float
                  Re-runs a single model on a single input.
                  Use the same model clients you use in your primary workflow.

Both are injected into CorrectionRunner.__init__, so tests use stubs.

Usage
-----
    from manifold.testing.correction import CorrectionRunner

    async def call_llm(prompt: str) -> str:
        response = await anthropic_client.messages.create(...)
        return response.content[0].text

    async def run_model(input_data: dict, criteria_hint: str, model_id: str) -> float:
        # Call your real model with the criteria hint as system context
        ...

    runner = CorrectionRunner(
        llm_caller=call_llm,
        model_runner=run_model,
        model_ids=["gpt-4o", "gemini-flash", "llama-3.3", "mistral-small"],
        baseline_store=baseline,
    )

    # In harness:
    harness = HMMVTestHarness(..., correction_runner=runner)
"""

from __future__ import annotations

import json
import logging
import statistics
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from manifold.testing.models import (
    DriftSignal,
    DriftType,
    ProposalStatus,
    SpecProposal,
    _compute_mad,
)

logger = logging.getLogger(__name__)

# Protocols as type aliases (runtime duck-typing, no ABC overhead)
LLMCaller   = Callable[[str], Awaitable[str]]
ModelRunner = Callable[[dict, str, str], Awaitable[float]]
# ModelRunner(input_data, criteria_hint, model_id) → score


# ---------------------------------------------------------------------------
# Internal data structures (pipeline-private)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CorrectionAnalysis:
    """
    Pure enrichment of a DriftSignal. No IO.

    Produced by step 1. Feeds step 2 (hypothesis generation).
    """
    signal_id:          str
    drift_type:         DriftType
    input_class:        str
    triggering_input:   dict

    # What the models said
    model_scores:       dict[str, float]
    observed_mad:       float
    expected_mad:       float | None
    outlier_model:      str | None

    # Derived stats
    agreeing_models:    list[str]          # models whose scores are close to consensus
    disagreeing_models: list[str]          # models far from consensus

    # Context
    baseline_records:   int
    implicated_specs:   list[str]          # spec_ids likely responsible

    # Diagnosis
    probable_cause:     str                # human-readable single sentence
    target_spec_id:     str                # which spec to target
    confidence_in_diagnosis: float         # [0, 1]


@dataclass(frozen=True)
class Hypothesis:
    """
    A proposed correction. Produced by step 2 (LLM call).
    """
    proposed_change:    str    # human-readable description
    proposed_spec_code: str    # the actual implementation (or recommendation)
    hypothesis:         str    # why this change should restore convergence
    target_spec_id:     str
    llm_raw_response:   str    # preserved for audit


@dataclass(frozen=True)
class ValidationResult:
    """
    Outcome of re-running models with the proposed criteria. Produced by step 3.
    """
    validated:             bool
    mad_before:            float
    mad_after:             float | None
    model_scores_after:    dict[str, float]
    models_converged:      int               # models within 2× expected MAD
    n_models_tested:       int
    validation_note:       str               # why validated/rejected


# ---------------------------------------------------------------------------
# Step 1 — Analyze
# ---------------------------------------------------------------------------

def analyze(signal: DriftSignal) -> CorrectionAnalysis:
    """
    Pure function. Enriches a DriftSignal into a CorrectionAnalysis.

    Identifies agreeing vs disagreeing models, picks the most likely
    target spec from implicated_specs, and writes a human-readable
    probable_cause sentence.
    """
    scores     = signal.model_scores
    values     = list(scores.values())
    consensus  = statistics.median(values)
    spread     = statistics.stdev(values) if len(values) > 1 else 0.0

    agreeing     = [m for m, s in scores.items() if abs(s - consensus) <= spread]
    disagreeing  = [m for m, s in scores.items() if abs(s - consensus) > spread]

    # Target spec: prefer the first implicated spec, fallback to sentinel
    target = signal.implicated_specs[0] if signal.implicated_specs else "unknown_spec"

    if signal.drift_type == DriftType.MODEL_OUTLIER:
        cause = (
            f"Model '{signal.outlier_model}' diverges from the other "
            f"{len(agreeing)} models on input class '{signal.input_class}'. "
            "Likely cause: model update, weight drift, or architecture change. "
            "Spec change is probably NOT needed — model audit is."
        )
        confidence = 0.85 if signal.outlier_model else 0.6

    elif signal.drift_type == DriftType.CRITERIA_GAP:
        cause = (
            f"Models split into {len(agreeing)} agreeing and "
            f"{len(disagreeing)} disagreeing on input class '{signal.input_class}'. "
            f"Observed MAD {signal.observed_mad:.3f} is "
            f"{signal.observed_mad / signal.expected_mad:.1f}× "
            f"the expected {signal.expected_mad:.3f}. "
            "Likely cause: the current spec does not adequately define "
            "classification criteria for this input type."
        )
        confidence = 0.75

    else:
        cause = (
            f"Drift type UNKNOWN on input class '{signal.input_class}'. "
            f"Insufficient baseline data ({signal.baseline_records} records) to diagnose. "
            "Investigation required before proposing a change."
        )
        confidence = 0.3

    return CorrectionAnalysis(
        signal_id=signal.signal_id,
        drift_type=signal.drift_type,
        input_class=signal.input_class,
        triggering_input=signal.triggering_input,
        model_scores=scores,
        observed_mad=signal.observed_mad,
        expected_mad=signal.expected_mad,
        outlier_model=signal.outlier_model,
        agreeing_models=agreeing,
        disagreeing_models=disagreeing,
        baseline_records=signal.baseline_records,
        implicated_specs=signal.implicated_specs,
        probable_cause=cause,
        target_spec_id=target,
        confidence_in_diagnosis=confidence,
    )


# ---------------------------------------------------------------------------
# Step 2 — Generate hypothesis (LLM)
# ---------------------------------------------------------------------------

def _build_prompt(analysis: CorrectionAnalysis, current_spec_code: str) -> str:
    scores_fmt = "\n".join(
        f"  {m}: {s:+.3f}" for m, s in sorted(analysis.model_scores.items())
    )
    agreeing_fmt    = ", ".join(analysis.agreeing_models)   or "none"
    disagreeing_fmt = ", ".join(analysis.disagreeing_models) or "none"

    if analysis.drift_type == DriftType.MODEL_OUTLIER:
        task = f"""\
One model ('{analysis.outlier_model}') diverges while others agree.
This is a MODEL HEALTH issue, not a criteria gap.

Your task:
1. Confirm whether the evidence supports a model drift diagnosis.
2. Recommend what action to take (audit, replace, weight-reduce the outlier model).
3. State clearly whether a spec code change is needed (almost certainly: NO).

proposed_spec_code should be a comment-only Python block explaining what to do:
    # Model audit recommendation: ...
    # No criteria change required.
"""
    elif analysis.drift_type == DriftType.CRITERIA_GAP:
        task = f"""\
All models diverge from each other on input class '{analysis.input_class}'.
This is a CRITERIA GAP — the current spec does not adequately cover this input type.

Your task:
1. Analyse what is ambiguous about the triggering input.
2. Propose a concrete, objective, verifiable criteria addition or modification.
3. Write proposed_spec_code as a Python class fragment (the new/modified evaluate() logic).

The proposed criteria MUST be:
- Objective (checkable by diverse models independently)
- Specific (not vague like "consider context")
- Additive (extend the spec, do not rewrite it entirely)
"""
    else:
        task = """\
Drift type is UNKNOWN. Insufficient baseline data to diagnose.
Propose a CONSERVATIVE investigation action — do NOT propose spec code changes.
proposed_spec_code should explain what data to collect to diagnose the issue.
"""

    return f"""\
You are a classification spec engineer. A multi-model validation system has detected
that {len(analysis.model_scores)} architecturally diverse models diverged on a classification task.

═══ DRIFT SUMMARY ═══════════════════════════════════════════════════
Drift type       : {analysis.drift_type.value}
Input class      : {analysis.input_class}
Triggering input : {json.dumps(analysis.triggering_input, ensure_ascii=False)}
Observed MAD     : {analysis.observed_mad:.4f}  (expected: {analysis.expected_mad or "N/A"})
Baseline records : {analysis.baseline_records}

Model scores:
{scores_fmt}

Agreeing models    : {agreeing_fmt}
Disagreeing models : {disagreeing_fmt}

Probable cause: {analysis.probable_cause}

═══ CURRENT SPEC CODE ═══════════════════════════════════════════════
{current_spec_code}

═══ YOUR TASK ═══════════════════════════════════════════════════════
{task}

═══ RESPONSE FORMAT ═════════════════════════════════════════════════
Respond ONLY with a valid JSON object. No markdown, no preamble.

{{
  "proposed_change": "<2-3 sentence human-readable description of what changes and why>",
  "proposed_spec_code": "<Python code string — escape newlines as \\n>",
  "hypothesis": "<1-2 sentence explanation of why this change should restore convergence>",
  "target_spec_id": "<spec rule_id to modify — use '{analysis.target_spec_id}' unless you have a better target>"
}}
"""


async def generate_hypothesis(
    analysis: CorrectionAnalysis,
    llm_caller: LLMCaller,
    current_spec_code: str = "# Spec code not provided",
    max_retries: int = 2,
) -> Hypothesis | None:
    """
    Call the LLM to generate a correction hypothesis.

    Returns None if the LLM fails to produce parseable output after retries.
    """
    prompt = _build_prompt(analysis, current_spec_code)

    for attempt in range(1, max_retries + 1):
        try:
            raw = await llm_caller(prompt)
            parsed = _parse_llm_response(raw)
            if parsed:
                return Hypothesis(
                    proposed_change=parsed["proposed_change"],
                    proposed_spec_code=parsed["proposed_spec_code"],
                    hypothesis=parsed["hypothesis"],
                    target_spec_id=parsed.get("target_spec_id", analysis.target_spec_id),
                    llm_raw_response=raw,
                )
            logger.warning("Attempt %d: LLM response not parseable, retrying", attempt)
        except Exception as e:
            logger.warning("Attempt %d: LLM caller raised: %s", attempt, e)

    logger.error("All %d attempts failed for signal %s", max_retries, analysis.signal_id)
    return None


def _parse_llm_response(raw: str) -> dict | None:
    """
    Extract JSON from LLM response. Tolerates markdown code fences.
    Returns None if required fields are missing.
    """
    text = raw.strip()

    # Strip markdown fences if present
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first line (```json or ```) and last line (```)
        inner = [l for l in lines[1:] if l.strip() != "```"]
        text = "\n".join(inner).strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Try to find JSON object within larger text
        start = text.find("{")
        end   = text.rfind("}") + 1
        if start == -1 or end == 0:
            return None
        try:
            data = json.loads(text[start:end])
        except json.JSONDecodeError:
            return None

    required = {"proposed_change", "proposed_spec_code", "hypothesis"}
    if not required.issubset(data.keys()):
        logger.warning("LLM response missing fields: %s", required - data.keys())
        return None

    # Validate non-empty
    for key in required:
        if not data[key] or not str(data[key]).strip():
            logger.warning("LLM response has empty field: %s", key)
            return None

    return data


# ---------------------------------------------------------------------------
# Step 3 — Validate
# ---------------------------------------------------------------------------

async def validate(
    hypothesis: Hypothesis,
    signal: DriftSignal,
    model_runner: ModelRunner,
    model_ids: list[str],
    expected_mad: float | None = None,
    improvement_threshold: float = 0.3,
) -> ValidationResult:
    """
    Re-run all models on the triggering input with the proposed criteria
    as additional context. Measure whether MAD improves.

    For MODEL_OUTLIER: validates by computing MAD excluding the outlier.
    For CRITERIA_GAP: re-runs all models with proposed_spec_code as criteria hint.

    Args
    ----
    hypothesis              Proposed change from step 2.
    signal                  The original DriftSignal (has triggering_input and scores).
    model_runner            Async callable: (input_data, criteria_hint, model_id) → float.
    model_ids               All model IDs to test.
    expected_mad            Historical baseline MAD (from signal or snapshot).
    improvement_threshold   Fractional MAD reduction required to declare validated.
                            Default 0.3 = 30% reduction required.
    """
    mad_before = signal.observed_mad

    # ── Special case: MODEL_OUTLIER ────────────────────────────────────────
    # Validation = does MAD drop to normal when we exclude the outlier?
    # No model re-run needed — we already have the scores.
    if signal.drift_type == DriftType.MODEL_OUTLIER and signal.outlier_model:
        scores_without_outlier = {
            m: s for m, s in signal.model_scores.items()
            if m != signal.outlier_model
        }
        mad_without = _compute_mad(list(scores_without_outlier.values()))
        threshold   = (expected_mad or mad_before) * 2.0

        validated = mad_without <= threshold
        note = (
            f"MAD without '{signal.outlier_model}': {mad_without:.4f} "
            f"({'≤' if validated else '>'} threshold {threshold:.4f}). "
            + ("Model outlier confirmed — audit model." if validated
               else "MAD still high without outlier — may be CRITERIA_GAP instead.")
        )
        return ValidationResult(
            validated=validated,
            mad_before=mad_before,
            mad_after=mad_without,
            model_scores_after=scores_without_outlier,
            models_converged=len(scores_without_outlier) if validated else 0,
            n_models_tested=len(scores_without_outlier),
            validation_note=note,
        )

    # ── CRITERIA_GAP and UNKNOWN: re-run models ────────────────────────────
    if not signal.triggering_input:
        return ValidationResult(
            validated=False,
            mad_before=mad_before,
            mad_after=None,
            model_scores_after={},
            models_converged=0,
            n_models_tested=0,
            validation_note=(
                "Cannot validate: triggering_input is empty. "
                "Harness must populate DriftSignal.triggering_input."
            ),
        )

    # Run all models with proposed criteria as additional context
    criteria_hint = (
        f"Apply the following updated classification criteria:\n\n"
        f"{hypothesis.proposed_spec_code}\n\n"
        f"Rationale: {hypothesis.hypothesis}"
    )

    scores_after: dict[str, float] = {}
    failed_models: list[str] = []

    for model_id in model_ids:
        try:
            score = await model_runner(signal.triggering_input, criteria_hint, model_id)
            scores_after[model_id] = score
        except Exception as e:
            logger.warning("Model '%s' failed during validation: %s", model_id, e)
            failed_models.append(model_id)

    if not scores_after:
        return ValidationResult(
            validated=False,
            mad_before=mad_before,
            mad_after=None,
            model_scores_after={},
            models_converged=0,
            n_models_tested=0,
            validation_note=f"All models failed during validation: {failed_models}",
        )

    mad_after  = _compute_mad(list(scores_after.values()))
    reduction  = (mad_before - mad_after) / mad_before if mad_before > 0 else 0.0
    validated  = reduction >= improvement_threshold

    # Count converged models: within 2× expected MAD of consensus
    if expected_mad and expected_mad > 0:
        consensus = statistics.median(list(scores_after.values()))
        converged = sum(
            1 for s in scores_after.values()
            if abs(s - consensus) <= expected_mad * 2
        )
    else:
        converged = len(scores_after)

    note = (
        f"MAD {mad_before:.4f} → {mad_after:.4f} "
        f"({reduction * 100:+.1f}% change, threshold {improvement_threshold * 100:.0f}%). "
    )
    if failed_models:
        note += f"Failed models (excluded): {failed_models}. "
    note += (
        f"{converged}/{len(scores_after)} models converged after proposed change. "
        + ("✓ Validated." if validated else "✗ Insufficient improvement — proposal rejected.")
    )

    return ValidationResult(
        validated=validated,
        mad_before=mad_before,
        mad_after=mad_after,
        model_scores_after=scores_after,
        models_converged=converged,
        n_models_tested=len(scores_after),
        validation_note=note,
    )


# ---------------------------------------------------------------------------
# CorrectionRunner — the public interface
# ---------------------------------------------------------------------------

class CorrectionRunner:
    """
    Real correction runner. Replaces NoOpCorrectionRunner.

    Executes: analyze → generate_hypothesis → validate → assemble SpecProposal.

    All four steps are logged. If any non-final step fails, the runner
    returns None (not an exception) — the EventConsumer handles the
    CORRECTION_FAILED event.

    Args
    ----
    llm_caller          Async callable: (prompt: str) → str.
    model_runner        Async callable: (input_data, criteria_hint, model_id) → float.
    model_ids           All model IDs used in the primary workflow.
    baseline_store      For fetching current spec code (optional — uses placeholder if None).
    improvement_threshold  MAD reduction fraction required to validate. Default 0.3.
    max_llm_retries     How many times to retry a failed LLM call. Default 2.
    """

    def __init__(
        self,
        llm_caller:    LLMCaller,
        model_runner:  ModelRunner,
        model_ids:     list[str],
        baseline_store: Any = None,          # BaselineStore (optional)
        current_spec_codes: dict[str, str] | None = None,
        improvement_threshold: float = 0.3,
        max_llm_retries: int = 2,
    ) -> None:
        self._llm            = llm_caller
        self._model_runner   = model_runner
        self._model_ids      = model_ids
        self._baseline       = baseline_store
        self._spec_codes     = current_spec_codes or {}
        self._threshold      = improvement_threshold
        self._max_retries    = max_llm_retries

    async def run(self, signal: DriftSignal) -> SpecProposal | None:
        """
        Full correction pipeline.

        Returns a SpecProposal (proposal_status=VALIDATED or REJECTED)
        or None if the pipeline itself failed (e.g. LLM unreachable).
        """
        logger.info(
            "CorrectionRunner: starting for signal_id=%s type=%s class=%s",
            signal.signal_id, signal.drift_type.value, signal.input_class,
        )

        # ── Step 1: Analyze ─────────────────────────────────────────────────
        analysis = analyze(signal)
        logger.info(
            "Analysis: cause=%s confidence=%.2f target_spec=%s",
            analysis.drift_type.value,
            analysis.confidence_in_diagnosis,
            analysis.target_spec_id,
        )

        # ── Step 2: Generate hypothesis ─────────────────────────────────────
        current_code = self._spec_codes.get(
            analysis.target_spec_id,
            f"# Spec '{analysis.target_spec_id}' code not available"
        )
        hypothesis = await generate_hypothesis(
            analysis, self._llm, current_code, self._max_retries
        )
        if hypothesis is None:
            logger.error(
                "Hypothesis generation failed for signal_id=%s", signal.signal_id
            )
            return None
        logger.info(
            "Hypothesis: target=%s change=%s",
            hypothesis.target_spec_id,
            hypothesis.proposed_change[:80] + "..." if len(hypothesis.proposed_change) > 80
            else hypothesis.proposed_change,
        )

        # ── Step 3: Validate ────────────────────────────────────────────────
        validation = await validate(
            hypothesis=hypothesis,
            signal=signal,
            model_runner=self._model_runner,
            model_ids=self._model_ids,
            expected_mad=signal.expected_mad,
            improvement_threshold=self._threshold,
        )
        logger.info(
            "Validation: validated=%s mad_before=%.4f mad_after=%s note=%s",
            validation.validated,
            validation.mad_before,
            f"{validation.mad_after:.4f}" if validation.mad_after is not None else "N/A",
            validation.validation_note,
        )

        # ── Step 4: Assemble SpecProposal ────────────────────────────────────
        status = ProposalStatus.VALIDATED if validation.validated else ProposalStatus.REJECTED

        proposal = SpecProposal(
            proposal_id=str(uuid.uuid4()),
            created_at=datetime.now(timezone.utc),
            triggered_by_signal_id=signal.signal_id,
            target_spec_id=hypothesis.target_spec_id,
            current_spec_version="unknown",      # caller can enrich from registry
            proposed_change=hypothesis.proposed_change,
            proposed_spec_code=hypothesis.proposed_spec_code,
            hypothesis=hypothesis.hypothesis,
            drift_examples=[signal.input_fingerprint],
            convergence_examples=signal.representative_fps,
            proposal_status=status,
            validation_mad_before=validation.mad_before,
            validation_mad_after=validation.mad_after,
            models_converged_after=validation.models_converged,
        )

        logger.info(
            "Proposal assembled: proposal_id=%s status=%s improvement=%.4f",
            proposal.proposal_id,
            status.value,
            proposal.mad_improvement or 0.0,
        )
        return proposal
