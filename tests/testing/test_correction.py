"""
Tests for manifold.testing.correction

All steps are tested independently using stubs — no real LLM or model
calls. The CorrectionRunner integration test exercises the full pipeline
end-to-end with deterministic fakes.

Coverage:
- analyze(): pure function, all three drift types
- _parse_llm_response(): JSON parsing, fence stripping, missing fields
- generate_hypothesis(): happy path, LLM failure retry, all-fail returns None
- validate(): MODEL_OUTLIER (no re-run), CRITERIA_GAP improvement, degradation,
              empty triggering_input guard
- CorrectionRunner.run(): CRITERIA_GAP validated, CRITERIA_GAP rejected,
                          MODEL_OUTLIER, LLM failure → None
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import pytest

from manifold.testing.correction import (
    CorrectionRunner,
    CorrectionAnalysis,
    Hypothesis,
    ValidationResult,
    analyze,
    generate_hypothesis,
    validate,
    _parse_llm_response,
)
from manifold.testing.models import (
    DriftSignal,
    DriftType,
    ProposalStatus,
    SpecProposal,
    _compute_mad,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MODEL_IDS = ["gpt", "gemini", "llama", "mistral"]


def make_signal(
    drift_type: DriftType = DriftType.CRITERIA_GAP,
    model_scores: dict | None = None,
    outlier_model: str | None = None,
    triggering_input: dict | None = None,
    expected_mad: float = 0.04,
    baseline_records: int = 50,
) -> DriftSignal:
    if model_scores is None:
        if drift_type == DriftType.MODEL_OUTLIER:
            model_scores = {"gpt": 0.80, "gemini": 0.78, "llama": 0.82, "mistral": -0.90}
            outlier_model = outlier_model or "mistral"
        else:
            model_scores = {"gpt": 0.80, "gemini": 0.80, "llama": -0.80, "mistral": -0.80}

    return DriftSignal(
        signal_id=str(uuid.uuid4()),
        run_id=str(uuid.uuid4()),
        timestamp=datetime.now(timezone.utc),
        drift_type=drift_type,
        input_fingerprint="abc123",
        input_class="ngo_religious",
        model_scores=model_scores,
        observed_mad=_compute_mad(list(model_scores.values())),
        expected_mad=expected_mad,
        baseline_records=baseline_records,
        outlier_model=outlier_model,
        implicated_specs=["classify_spec", "threshold_spec"],
        representative_fps=["fp1", "fp2", "fp3"],
        triggering_input=triggering_input or {"name": "Caritas Berlin", "type": "welfare"},
    )


def make_hypothesis(target: str = "classify_spec") -> Hypothesis:
    return Hypothesis(
        proposed_change="Add explicit criteria for welfare organisations in religious context.",
        proposed_spec_code=(
            "# Welfare orgs with religious affiliation → classify as ngo_religious\n"
            "if 'welfare' in candidate.lower() and 'religious' in context.get_data('tags', []):\n"
            "    return SpecResult.ok(...)"
        ),
        hypothesis="Welfare orgs with partial religious affiliation cause model splits. "
                   "Explicit criteria should restore convergence.",
        target_spec_id=target,
        llm_raw_response='{"proposed_change":"...","proposed_spec_code":"...","hypothesis":"..."}',
    )


# ---------------------------------------------------------------------------
# Step 1 — analyze()
# ---------------------------------------------------------------------------

class TestAnalyze:
    def test_criteria_gap_sets_cause(self):
        sig = make_signal(DriftType.CRITERIA_GAP)
        a = analyze(sig)
        assert a.drift_type == DriftType.CRITERIA_GAP
        assert "CRITERIA_GAP" in a.probable_cause or "split" in a.probable_cause.lower()

    def test_model_outlier_names_outlier(self):
        sig = make_signal(DriftType.MODEL_OUTLIER)
        a = analyze(sig)
        assert "mistral" in a.probable_cause

    def test_unknown_has_low_confidence(self):
        sig = make_signal(DriftType.UNKNOWN)
        a = analyze(sig)
        assert a.confidence_in_diagnosis < 0.5

    def test_model_outlier_high_confidence(self):
        sig = make_signal(DriftType.MODEL_OUTLIER)
        a = analyze(sig)
        assert a.confidence_in_diagnosis > 0.7

    def test_target_spec_from_implicated(self):
        sig = make_signal()
        a = analyze(sig)
        assert a.target_spec_id == "classify_spec"  # first in list

    def test_target_spec_fallback_when_empty(self):
        sig = make_signal()
        from dataclasses import replace
        sig = replace(sig, implicated_specs=[])
        a = analyze(sig)
        assert a.target_spec_id == "unknown_spec"

    def test_agreeing_disagreeing_populated(self):
        sig = make_signal(DriftType.CRITERIA_GAP)
        a = analyze(sig)
        assert len(a.agreeing_models) > 0
        assert len(a.disagreeing_models) > 0
        # All model IDs appear exactly once across the two lists
        all_ids = set(a.agreeing_models) | set(a.disagreeing_models)
        assert all_ids == set(sig.model_scores.keys())

    def test_pure_no_side_effects(self):
        sig = make_signal()
        a1 = analyze(sig)
        a2 = analyze(sig)
        assert a1.probable_cause == a2.probable_cause


# ---------------------------------------------------------------------------
# LLM response parsing
# ---------------------------------------------------------------------------

class TestParseLLMResponse:
    def _valid_json(self, **overrides) -> str:
        data = {
            "proposed_change": "Add welfare criteria.",
            "proposed_spec_code": "# code",
            "hypothesis": "This will converge.",
            "target_spec_id": "spec_a",
            **overrides,
        }
        return json.dumps(data)

    def test_clean_json(self):
        result = _parse_llm_response(self._valid_json())
        assert result["proposed_change"] == "Add welfare criteria."

    def test_strips_markdown_fences(self):
        raw = "```json\n" + self._valid_json() + "\n```"
        result = _parse_llm_response(raw)
        assert result is not None

    def test_strips_plain_fences(self):
        raw = "```\n" + self._valid_json() + "\n```"
        result = _parse_llm_response(raw)
        assert result is not None

    def test_json_embedded_in_text(self):
        raw = "Here is the response: " + self._valid_json() + " Thank you."
        result = _parse_llm_response(raw)
        assert result is not None

    def test_missing_field_returns_none(self):
        raw = json.dumps({"proposed_change": "x", "hypothesis": "y"})
        assert _parse_llm_response(raw) is None

    def test_empty_field_returns_none(self):
        raw = self._valid_json(proposed_change="")
        assert _parse_llm_response(raw) is None

    def test_invalid_json_returns_none(self):
        assert _parse_llm_response("not json at all") is None

    def test_preserves_target_spec_id(self):
        raw = self._valid_json(target_spec_id="my_spec")
        result = _parse_llm_response(raw)
        assert result["target_spec_id"] == "my_spec"


# ---------------------------------------------------------------------------
# Step 2 — generate_hypothesis()
# ---------------------------------------------------------------------------

class TestGenerateHypothesis:
    def _mock_llm(self, response: str):
        """Returns a stub LLM caller that always responds with `response`."""
        async def caller(prompt: str) -> str:
            return response
        return caller

    def _valid_llm_response(self, **overrides) -> str:
        data = {
            "proposed_change": "Add welfare/religious intersection criterion.",
            "proposed_spec_code": "# if welfare and religious → classify ngo_religious",
            "hypothesis": "Models diverge on this edge case. Explicit criterion fixes it.",
            "target_spec_id": "classify_spec",
            **overrides,
        }
        return json.dumps(data)

    @pytest.mark.asyncio
    async def test_happy_path(self):
        sig = make_signal()
        analysis = analyze(sig)
        h = await generate_hypothesis(analysis, self._mock_llm(self._valid_llm_response()))
        assert h is not None
        assert h.proposed_change == "Add welfare/religious intersection criterion."

    @pytest.mark.asyncio
    async def test_preserves_raw_response(self):
        sig = make_signal()
        analysis = analyze(sig)
        raw = self._valid_llm_response()
        h = await generate_hypothesis(analysis, self._mock_llm(raw))
        assert h.llm_raw_response == raw

    @pytest.mark.asyncio
    async def test_retries_on_bad_response_then_succeeds(self):
        call_count = [0]
        good = self._valid_llm_response()

        async def flaky_llm(prompt: str) -> str:
            call_count[0] += 1
            if call_count[0] == 1:
                return "not json"
            return good

        analysis = analyze(make_signal())
        h = await generate_hypothesis(analysis, flaky_llm, max_retries=2)
        assert h is not None
        assert call_count[0] == 2

    @pytest.mark.asyncio
    async def test_all_retries_fail_returns_none(self):
        async def bad_llm(prompt: str) -> str:
            return "not json ever"

        analysis = analyze(make_signal())
        h = await generate_hypothesis(analysis, bad_llm, max_retries=2)
        assert h is None

    @pytest.mark.asyncio
    async def test_llm_exception_counts_as_failure(self):
        async def exploding_llm(prompt: str) -> str:
            raise RuntimeError("LLM unavailable")

        analysis = analyze(make_signal())
        h = await generate_hypothesis(analysis, exploding_llm, max_retries=2)
        assert h is None

    @pytest.mark.asyncio
    async def test_uses_fallback_target_if_llm_omits_it(self):
        """If LLM doesn't return target_spec_id, falls back to analysis.target_spec_id."""
        data = {
            "proposed_change": "x",
            "proposed_spec_code": "# x",
            "hypothesis": "y",
            # target_spec_id deliberately omitted
        }
        analysis = analyze(make_signal())
        h = await generate_hypothesis(analysis, self._mock_llm(json.dumps(data)))
        assert h is not None
        assert h.target_spec_id == analysis.target_spec_id


# ---------------------------------------------------------------------------
# Step 3 — validate()
# ---------------------------------------------------------------------------

class TestValidate:
    def _make_model_runner(self, scores_by_model: dict[str, float]):
        """Stub model runner returning predefined scores."""
        async def runner(input_data: dict, criteria_hint: str, model_id: str) -> float:
            return scores_by_model[model_id]
        return runner

    @pytest.mark.asyncio
    async def test_model_outlier_validated_without_rerun(self):
        sig = make_signal(DriftType.MODEL_OUTLIER)
        # mistral is the outlier; without it MAD should be very low
        h = make_hypothesis()
        result = await validate(h, sig, None, MODEL_IDS, expected_mad=0.04)
        assert result.validated is True
        assert "mistral" not in result.model_scores_after

    @pytest.mark.asyncio
    async def test_model_outlier_not_validated_if_mad_still_high(self):
        # All models diverge — excluding outlier doesn't help
        sig = make_signal(
            DriftType.MODEL_OUTLIER,
            model_scores={"gpt": 0.80, "gemini": -0.80, "llama": 0.80, "mistral": -0.90},
            outlier_model="mistral",
        )
        h = make_hypothesis()
        result = await validate(h, sig, None, MODEL_IDS, expected_mad=0.04)
        assert result.validated is False

    @pytest.mark.asyncio
    async def test_criteria_gap_validated_on_improvement(self):
        # After proposed criteria, models converge: MAD goes from ~0.8 to ~0.02
        sig = make_signal(DriftType.CRITERIA_GAP, expected_mad=0.04)
        h = make_hypothesis()
        # Tight scores after correction
        runner = self._make_model_runner({"gpt": 0.79, "gemini": 0.80, "llama": 0.81, "mistral": 0.78})
        result = await validate(h, sig, runner, MODEL_IDS, expected_mad=0.04)
        assert result.validated is True
        assert result.mad_after < result.mad_before

    @pytest.mark.asyncio
    async def test_criteria_gap_rejected_on_no_improvement(self):
        sig = make_signal(DriftType.CRITERIA_GAP, expected_mad=0.04)
        h = make_hypothesis()
        # Scores still diverge after correction
        runner = self._make_model_runner({"gpt": 0.80, "gemini": 0.80, "llama": -0.80, "mistral": -0.80})
        result = await validate(h, sig, runner, MODEL_IDS, expected_mad=0.04)
        assert result.validated is False

    @pytest.mark.asyncio
    async def test_empty_triggering_input_guard(self):
        from dataclasses import replace
        sig = make_signal(DriftType.CRITERIA_GAP)
        sig = replace(sig, triggering_input={})
        h = make_hypothesis()
        result = await validate(h, sig, None, MODEL_IDS)
        assert result.validated is False
        assert "triggering_input is empty" in result.validation_note

    @pytest.mark.asyncio
    async def test_model_runner_exception_excluded_gracefully(self):
        sig = make_signal(DriftType.CRITERIA_GAP, expected_mad=0.04)
        h = make_hypothesis()

        async def flaky_runner(input_data, criteria_hint, model_id):
            if model_id == "llama":
                raise RuntimeError("model timeout")
            return {"gpt": 0.79, "gemini": 0.80, "mistral": 0.78}[model_id]

        result = await validate(h, sig, flaky_runner, MODEL_IDS, expected_mad=0.04)
        assert "llama" not in result.model_scores_after
        assert result.n_models_tested == 3

    @pytest.mark.asyncio
    async def test_all_models_fail_returns_not_validated(self):
        sig = make_signal(DriftType.CRITERIA_GAP)
        h = make_hypothesis()

        async def broken_runner(input_data, criteria_hint, model_id):
            raise RuntimeError("all broken")

        result = await validate(h, sig, broken_runner, MODEL_IDS)
        assert result.validated is False
        assert result.mad_after is None


# ---------------------------------------------------------------------------
# CorrectionRunner — full pipeline
# ---------------------------------------------------------------------------

class TestCorrectionRunner:
    def _make_runner(
        self,
        llm_response: str | None = None,
        scores_after: dict[str, float] | None = None,
    ) -> CorrectionRunner:
        if llm_response is None:
            llm_response = json.dumps({
                "proposed_change": "Add explicit edge-case criterion.",
                "proposed_spec_code": "# Explicit criterion: welfare + religious → ngo_religious",
                "hypothesis": "Models converge once ambiguity is resolved.",
                "target_spec_id": "classify_spec",
            })

        async def llm(prompt: str) -> str:
            return llm_response

        if scores_after is None:
            scores_after = {"gpt": 0.79, "gemini": 0.80, "llama": 0.81, "mistral": 0.78}

        async def model_runner(input_data, criteria_hint, model_id) -> float:
            return scores_after[model_id]

        return CorrectionRunner(
            llm_caller=llm,
            model_runner=model_runner,
            model_ids=MODEL_IDS,
            improvement_threshold=0.2,
        )

    @pytest.mark.asyncio
    async def test_criteria_gap_produces_validated_proposal(self):
        runner = self._make_runner()
        signal = make_signal(DriftType.CRITERIA_GAP, expected_mad=0.04)
        proposal = await runner.run(signal)

        assert proposal is not None
        assert proposal.proposal_status == ProposalStatus.VALIDATED
        assert proposal.triggered_by_signal_id == signal.signal_id
        assert proposal.target_spec_id == "classify_spec"
        assert proposal.validation_mad_before > proposal.validation_mad_after

    @pytest.mark.asyncio
    async def test_criteria_gap_still_diverging_produces_rejected_proposal(self):
        still_diverged = {"gpt": 0.80, "gemini": 0.80, "llama": -0.80, "mistral": -0.80}
        runner = self._make_runner(scores_after=still_diverged)
        signal = make_signal(DriftType.CRITERIA_GAP, expected_mad=0.04)
        proposal = await runner.run(signal)

        assert proposal is not None
        assert proposal.proposal_status == ProposalStatus.REJECTED

    @pytest.mark.asyncio
    async def test_model_outlier_produces_validated_proposal(self):
        runner = self._make_runner()
        signal = make_signal(DriftType.MODEL_OUTLIER)
        proposal = await runner.run(signal)

        # MODEL_OUTLIER validation excludes the outlier — should converge
        assert proposal is not None
        assert proposal.proposal_status == ProposalStatus.VALIDATED

    @pytest.mark.asyncio
    async def test_llm_failure_returns_none(self):
        async def bad_llm(prompt: str) -> str:
            raise RuntimeError("LLM down")

        async def model_runner(input_data, criteria_hint, model_id) -> float:
            return 0.8

        runner = CorrectionRunner(bad_llm, model_runner, MODEL_IDS, max_llm_retries=1)
        proposal = await runner.run(make_signal())
        assert proposal is None

    @pytest.mark.asyncio
    async def test_proposal_contains_full_audit_trail(self):
        runner = self._make_runner()
        signal = make_signal(DriftType.CRITERIA_GAP, expected_mad=0.04)
        proposal = await runner.run(signal)

        assert proposal is not None
        assert proposal.proposed_change
        assert proposal.proposed_spec_code
        assert proposal.hypothesis
        assert proposal.drift_examples      # at least the triggering fingerprint
        assert proposal.validation_mad_before is not None
        assert proposal.validation_mad_after is not None
        assert proposal.created_at.tzinfo == timezone.utc

    @pytest.mark.asyncio
    async def test_convergence_examples_from_signal(self):
        runner = self._make_runner()
        signal = make_signal()
        proposal = await runner.run(signal)
        assert proposal.convergence_examples == signal.representative_fps

    @pytest.mark.asyncio
    async def test_round_trip_serialization(self):
        runner = self._make_runner()
        signal = make_signal(DriftType.CRITERIA_GAP, expected_mad=0.04)
        proposal = await runner.run(signal)
        assert proposal is not None

        roundtripped = SpecProposal.from_dict(proposal.to_dict())
        assert roundtripped.proposal_id == proposal.proposal_id
        assert roundtripped.proposal_status == proposal.proposal_status
        assert roundtripped.validation_mad_before == proposal.validation_mad_before
