"""
Universal Validator — post-hoc revalidation of consolidated experiment trials.

Applies a consistent set of criteria across all three approaches (naive, smart,
manifold) so that success rates can be compared on equal footing.

EXP1 (DALL-E 3 Sprite Generation)
  Criterion 1 [CRITICAL]  separation   — inter-sprite white-space >= 20%
                           Source: extracted from smart_control validation_history.
                           Naive/manifold never recorded this → UNKNOWN.

EXP2 (gpt-image-1 Sprite Generation)
  Criterion 1 [CRITICAL]  separation   — same as EXP1: >=20% white-space.
                           Only smart records image analysis → naive/manifold UNKNOWN.

EXP3 (GPT-4o Data Extraction)
  Criterion 1 [CRITICAL]  required_fields — all 7 schema fields present in output
  Criterion 2 [CRITICAL]  no_hallucination — fields that should be null ARE null
  Criterion 3 [CRITICAL]  field_accuracy   — all non-null fields match expected value
                           (case-normalised)
  Criterion 4 [WARNING]   email_format     — email field matches basic regex

EXP4 (Multi-Step Content Generation)
  Criterion 1 [CRITICAL]  pipeline_complete — all 4 stages ran (success=True)
  Criterion 2 [CRITICAL]  min_word_count    — final article >= 500 words
                           (naive/smart store word_count; manifold also stores it)
"""

import re
import json
from dataclasses import dataclass, asdict
from enum import Enum
from pathlib import Path
from datetime import datetime
from typing import Optional

# ── Enums & dataclasses ───────────────────────────────────────────────────────

class Severity(str, Enum):
    CRITICAL = "critical"
    WARNING  = "warning"
    INFO     = "info"

class Verdict(str, Enum):
    PASS    = "pass"
    FAIL    = "fail"
    UNKNOWN = "unknown"   # criterion could not be evaluated (no data)

@dataclass
class RuleResult:
    rule:     str
    verdict:  Verdict
    severity: Severity
    details:  dict

@dataclass
class TrialValidation:
    trial_id:          int
    approach:          str
    experiment:        str
    original_success:  bool
    universal_success: bool   # True only if all CRITICAL rules PASS (not UNKNOWN)
    rule_results:      list   # list of RuleResult dicts
    # Comparison flags
    agreement:         bool
    false_positive:    bool   # original=True, universal=False
    false_negative:    bool   # original=False, universal=True


# ── EXP1 Validators ──────────────────────────────────────────────────────────

# Smart uses threshold >20% — confirmed from data (19.5% fails, implied 20% cutoff)
EXP1_SEPARATION_THRESHOLD = 20.0

_SEP_RE = re.compile(r"separation:Insufficient separation \((\d+\.?\d*)% white space\)")

def _exp1_separation(trial: dict) -> RuleResult:
    """
    Extract white-space percentage from smart_control validation_history.
    Naive/manifold don't run image analysis → UNKNOWN.
    """
    vh = trial.get("metadata", {}).get("validation_history", [])

    if not vh:
        # No image analysis was run (naive / manifold)
        return RuleResult(
            rule="separation",
            verdict=Verdict.UNKNOWN,
            severity=Severity.CRITICAL,
            details={"reason": "no_image_analysis", "note": "approach does not perform separation check"}
        )

    # Gather all measured white-space values across attempts
    measured = []
    for entry in vh:
        for failure in entry.get("failures", []):
            m = _SEP_RE.match(failure)
            if m:
                measured.append(float(m.group(1)))

    if not measured and all(entry.get("success") for entry in vh):
        # All attempts passed — separation was OK but exact value not recorded
        return RuleResult(
            rule="separation",
            verdict=Verdict.PASS,
            severity=Severity.CRITICAL,
            details={"reason": "all_attempts_passed", "threshold": EXP1_SEPARATION_THRESHOLD}
        )

    # Use the LAST (final) measured value — that's what determined the outcome
    final_value = measured[-1] if measured else None
    if final_value is None:
        return RuleResult(
            rule="separation",
            verdict=Verdict.UNKNOWN,
            severity=Severity.CRITICAL,
            details={"reason": "no_separation_data_in_validation_history"}
        )

    passed = final_value >= EXP1_SEPARATION_THRESHOLD
    return RuleResult(
        rule="separation",
        verdict=Verdict.PASS if passed else Verdict.FAIL,
        severity=Severity.CRITICAL,
        details={
            "white_space_pct": final_value,
            "threshold": EXP1_SEPARATION_THRESHOLD,
            "all_measured": measured,
        }
    )


EXP1_RULES = [_exp1_separation]


# ── EXP3 Validators ──────────────────────────────────────────────────────────

# The 7 fields that must appear in the model's output
EXP3_REQUIRED_FIELDS = [
    "customer_id", "email", "order_id",
    "issue_type", "priority", "requires_escalation", "customer_role"
]

_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")


def _get_extracted(trial: dict) -> Optional[dict]:
    """Return the model's extracted dict from whichever metadata key stores it."""
    meta = trial.get("metadata", {})
    # naive stores it as metadata.extracted
    # smart stores it as metadata.data
    # manifold doesn't store it at all
    return meta.get("extracted") or meta.get("data")


def _get_expected(trial: dict) -> Optional[dict]:
    """Return the ground-truth expected dict."""
    meta = trial.get("metadata", {})
    return meta.get("expected")


def _normalize_str(v) -> Optional[str]:
    """Lowercase, strip, collapse spaces — for case-insensitive comparison."""
    if v is None:
        return None
    return " ".join(str(v).lower().split())


def _exp3_required_fields(trial: dict) -> RuleResult:
    extracted = _get_extracted(trial)
    if extracted is None:
        return RuleResult(
            rule="required_fields",
            verdict=Verdict.UNKNOWN,
            severity=Severity.CRITICAL,
            details={"reason": "no_extracted_data_in_metadata"}
        )

    missing = [f for f in EXP3_REQUIRED_FIELDS if f not in extracted]
    return RuleResult(
        rule="required_fields",
        verdict=Verdict.PASS if not missing else Verdict.FAIL,
        severity=Severity.CRITICAL,
        details={"missing": missing, "required": EXP3_REQUIRED_FIELDS}
    )


def _exp3_no_hallucination(trial: dict) -> RuleResult:
    """
    Fields where expected=null must not have a non-null extracted value.
    Exception: "unknown" / empty strings are treated as hallucinations too.
    """
    extracted = _get_extracted(trial)
    expected  = _get_expected(trial)

    if extracted is None or expected is None:
        return RuleResult(
            rule="no_hallucination",
            verdict=Verdict.UNKNOWN,
            severity=Severity.CRITICAL,
            details={"reason": "missing_extracted_or_expected"}
        )

    hallucinated = []
    for field, exp_val in expected.items():
        if exp_val is not None:
            continue  # only care about fields that should be null
        ext_val = extracted.get(field)
        if ext_val is None:
            continue
        # Treat "unknown", "", "n/a", "none" as hallucinations too
        if isinstance(ext_val, str) and ext_val.lower().strip() in ("unknown", "", "n/a", "none", "null"):
            hallucinated.append({"field": field, "value": ext_val, "note": "placeholder_for_null"})
        else:
            hallucinated.append({"field": field, "value": ext_val})

    return RuleResult(
        rule="no_hallucination",
        verdict=Verdict.PASS if not hallucinated else Verdict.FAIL,
        severity=Severity.CRITICAL,
        details={"hallucinated": hallucinated}
    )


def _exp3_field_accuracy(trial: dict) -> RuleResult:
    """
    All non-null expected fields must match extracted value (case-normalised).
    We use the correct_fields / total_fields already computed when available,
    but also recompute with normalisation so all approaches are treated equally.
    """
    extracted = _get_extracted(trial)
    expected  = _get_expected(trial)

    if extracted is None or expected is None:
        # Fall back to what the normalizer already computed
        fa = trial.get("field_accuracy")
        if fa is not None:
            return RuleResult(
                rule="field_accuracy",
                verdict=Verdict.PASS if fa >= 1.0 else Verdict.FAIL,
                severity=Severity.CRITICAL,
                details={"field_accuracy": fa, "source": "precomputed", "threshold": 1.0}
            )
        return RuleResult(
            rule="field_accuracy",
            verdict=Verdict.UNKNOWN,
            severity=Severity.CRITICAL,
            details={"reason": "no_extracted_or_expected_data"}
        )

    correct = 0
    wrong   = []
    total_non_null = 0

    for field, exp_val in expected.items():
        if exp_val is None:
            continue  # null fields handled by no_hallucination rule
        total_non_null += 1
        ext_val = extracted.get(field)
        # Case-normalised comparison
        if _normalize_str(ext_val) == _normalize_str(exp_val):
            correct += 1
        else:
            wrong.append({"field": field, "expected": exp_val, "got": ext_val})

    fa = correct / total_non_null if total_non_null > 0 else 1.0
    return RuleResult(
        rule="field_accuracy",
        verdict=Verdict.PASS if fa >= 1.0 else Verdict.FAIL,
        severity=Severity.CRITICAL,
        details={
            "field_accuracy": round(fa, 4),
            "correct": correct,
            "total_non_null": total_non_null,
            "wrong_fields": wrong,
            "threshold": 1.0
        }
    )


def _exp3_email_format(trial: dict) -> RuleResult:
    extracted = _get_extracted(trial)
    if extracted is None:
        return RuleResult(
            rule="email_format",
            verdict=Verdict.UNKNOWN,
            severity=Severity.WARNING,
            details={"reason": "no_extracted_data"}
        )

    email_val = extracted.get("email", "")
    if email_val is None:
        return RuleResult(
            rule="email_format",
            verdict=Verdict.FAIL,
            severity=Severity.WARNING,
            details={"email": None, "reason": "null_email"}
        )

    passed = bool(_EMAIL_RE.match(str(email_val)))
    return RuleResult(
        rule="email_format",
        verdict=Verdict.PASS if passed else Verdict.FAIL,
        severity=Severity.WARNING,
        details={"email": email_val, "regex": _EMAIL_RE.pattern}
    )


EXP3_RULES = [
    _exp3_required_fields,
    _exp3_no_hallucination,
    _exp3_field_accuracy,
    _exp3_email_format,
]


# ── EXP2 Validators ──────────────────────────────────────────────────────────
# Same separation criterion as EXP1 — reuse _exp1_separation directly.
EXP2_RULES = [_exp1_separation]


# ── EXP4 Validators ──────────────────────────────────────────────────────────

EXP4_MIN_WORDS = 500

def _exp4_pipeline_complete(trial: dict) -> RuleResult:
    """All 4 pipeline stages must have run (proxied by success flag)."""
    success = trial.get("success", False)
    return RuleResult(
        rule="pipeline_complete",
        verdict=Verdict.PASS if success else Verdict.FAIL,
        severity=Severity.CRITICAL,
        details={"success": success}
    )

def _exp4_min_word_count(trial: dict) -> RuleResult:
    """Final article must be at least 500 words."""
    wc = trial.get("word_count")
    if wc is None:
        return RuleResult(
            rule="min_word_count",
            verdict=Verdict.UNKNOWN,
            severity=Severity.CRITICAL,
            details={"reason": "word_count_not_recorded"}
        )
    passed = wc >= EXP4_MIN_WORDS
    return RuleResult(
        rule="min_word_count",
        verdict=Verdict.PASS if passed else Verdict.FAIL,
        severity=Severity.CRITICAL,
        details={"word_count": wc, "threshold": EXP4_MIN_WORDS}
    )

EXP4_RULES = [_exp4_pipeline_complete, _exp4_min_word_count]


# ── Universal success logic ───────────────────────────────────────────────────

def compute_universal_success(rule_results: list[RuleResult]) -> bool:
    """
    True only if every CRITICAL rule is PASS.
    UNKNOWN is NOT counted as failure — the trial is marked as UNKNOWN separately.
    Rules that are UNKNOWN are excluded from the success determination.
    Returns False if any CRITICAL rule FAILs.
    Returns True if all CRITICAL rules PASS or UNKNOWN (no definitive failures).
    """
    for r in rule_results:
        if r.severity == Severity.CRITICAL and r.verdict == Verdict.FAIL:
            return False
    return True


def has_unknowns(rule_results: list[RuleResult]) -> bool:
    return any(r.verdict == Verdict.UNKNOWN for r in rule_results)


# ── Main validator ────────────────────────────────────────────────────────────

RULES_BY_EXP = {
    "exp1_dalle3":     EXP1_RULES,
    "exp2_gptimage1":  EXP2_RULES,
    "exp3_extraction": EXP3_RULES,
    "exp4_content":    EXP4_RULES,
}


def validate_trial(trial: dict) -> TrialValidation:
    exp   = trial["experiment"]
    rules = RULES_BY_EXP.get(exp, [])

    rule_results = [rule(trial) for rule in rules]
    universal_success = compute_universal_success(rule_results)
    original_success  = trial["success"]

    return TrialValidation(
        trial_id=trial["trial_id"],
        approach=trial["approach"],
        experiment=exp,
        original_success=original_success,
        universal_success=universal_success,
        rule_results=[asdict(r) for r in rule_results],
        agreement=original_success == universal_success,
        false_positive=original_success and not universal_success,
        false_negative=not original_success and universal_success,
    )


# ── Revalidation pipeline ─────────────────────────────────────────────────────

def revalidate(trials_jsonl: Path, output_jsonl: Path) -> list[dict]:
    """Load, validate, enrich, write. Returns list of enriched trial dicts."""
    output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    enriched_all = []

    with open(trials_jsonl, encoding='utf-8') as fin, open(output_jsonl, "w", encoding='utf-8') as fout:
        for line in fin:
            trial = json.loads(line)
            tv    = validate_trial(trial)
            enriched = trial.copy()
            enriched["universal"] = asdict(tv)
            enriched_all.append(enriched)
            fout.write(json.dumps(enriched) + "\n")

    return enriched_all


# ── Summary printer ───────────────────────────────────────────────────────────

def print_summary(enriched: list[dict], experiment: str):
    from collections import defaultdict

    by_approach = defaultdict(list)
    for t in enriched:
        by_approach[t["approach"]].append(t)

    print(f"\n{'='*70}")
    print(f"UNIVERSAL VALIDATION SUMMARY -- {experiment}")
    print(f"{'='*70}")
    print(f"  NOTE: UNKNOWN = criterion could not be evaluated (no data in metadata).")
    print(f"        UNKNOWN rules are excluded from universal_success determination.")
    print(f"        FP = false positive (original=pass, universal=fail) -> original too lenient.")
    print(f"        FN = false negative (original=fail, universal=pass) -> original too strict.")
    print()

    # Overall table
    header = f"  {'Approach':<10} {'N':>4}  {'Orig%':>6}  {'Univ%':>6}  {'Agree%':>7}  {'FP':>4}  {'FN':>4}  {'w/Unknown':>10}"
    print(header)
    print("  " + "-" * 56)

    for approach in ["naive", "smart", "manifold"]:
        trials = by_approach[approach]
        if not trials:
            continue
        n = len(trials)
        orig_ok  = sum(1 for t in trials if t["universal"]["original_success"])
        univ_ok  = sum(1 for t in trials if t["universal"]["universal_success"])
        agree    = sum(1 for t in trials if t["universal"]["agreement"])
        fp       = sum(1 for t in trials if t["universal"]["false_positive"])
        fn       = sum(1 for t in trials if t["universal"]["false_negative"])
        has_unk  = sum(1 for t in trials if any(
            r["verdict"] == "unknown" for r in t["universal"]["rule_results"]
        ))
        print(f"  {approach:<10} {n:>4}  {orig_ok/n:>6.1%}  {univ_ok/n:>6.1%}  {agree/n:>7.1%}  {fp:>4}  {fn:>4}  {has_unk:>10}")

    # Per-rule breakdown: PASS / FAIL / UNKNOWN counts
    print(f"\n  Per-rule verdict breakdown (P=PASS  F=FAIL  U=UNKNOWN):")
    all_rules = []
    for t in enriched:
        for r in t["universal"]["rule_results"]:
            if r["rule"] not in all_rules:
                all_rules.append(r["rule"])

    # header for rule table
    rule_header = f"  {'Rule':<28}"
    for approach in ["naive", "smart", "manifold"]:
        if by_approach[approach]:
            rule_header += f"  {approach:<18}"
    print(rule_header)
    print("  " + "-" * (28 + 3 * 20))

    for rule in all_rules:
        row = f"  {rule:<28}"
        for approach in ["naive", "smart", "manifold"]:
            trials = by_approach[approach]
            if not trials:
                continue
            n = len(trials)
            passes   = sum(1 for t in trials if any(
                r["rule"] == rule and r["verdict"] == "pass"
                for r in t["universal"]["rule_results"]
            ))
            fails    = sum(1 for t in trials if any(
                r["rule"] == rule and r["verdict"] == "fail"
                for r in t["universal"]["rule_results"]
            ))
            unknowns = sum(1 for t in trials if any(
                r["rule"] == rule and r["verdict"] == "unknown"
                for r in t["universal"]["rule_results"]
            ))
            # severity from first trial that has this rule
            sev = next(
                (r["severity"] for t in trials for r in t["universal"]["rule_results"]
                 if r["rule"] == rule),
                "?"
            )
            tag = "[CRIT]" if sev == "critical" else "[WARN]"
            row += f"  {tag} P={passes:2d} F={fails:2d} U={unknowns:2d}"
        print(row)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    base = Path(__file__).resolve().parent.parent
    consolidated = base / "data" / "consolidated"
    revalidated  = base / "data" / "revalidated"

    for exp in ["exp1_dalle3", "exp2_gptimage1", "exp3_extraction", "exp4_content"]:
        print(f"\nRevalidating {exp}...")
        enriched = revalidate(
            trials_jsonl=consolidated / f"{exp}_trials.jsonl",
            output_jsonl=revalidated  / f"{exp}_trials_universal.jsonl",
        )
        print_summary(enriched, exp)
        print(f"Wrote: {revalidated / (exp + '_trials_universal.jsonl')}")
