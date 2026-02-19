"""
Consolidate raw experiment result files into a normalized schema.

Reads the 12 authoritative result files for EXP1, EXP2, EXP3, EXP4 and writes:
  data/consolidated/exp1_dalle3_trials.jsonl
  data/consolidated/exp2_gptimage1_trials.jsonl
  data/consolidated/exp3_extraction_trials.jsonl
  data/consolidated/exp4_content_trials.jsonl
  (+ matching _summary.json for each)

Run from any directory:
  python scripts/consolidate.py
"""

import json
from dataclasses import dataclass, asdict, field
from typing import Optional
from datetime import datetime
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────
SCRIPTS_DIR = Path(__file__).resolve().parent      # manifold/experiments/scripts/
EXPERIMENTS_DIR = SCRIPTS_DIR.parent               # manifold/experiments/
REPO_ROOT = EXPERIMENTS_DIR.parent                 # manifold/
DATA_OUT = EXPERIMENTS_DIR / "data" / "consolidated"
DATA_OUT.mkdir(parents=True, exist_ok=True)

# Authoritative source files (immutable — never written to)
SOURCES = {
    "exp1_dalle3": {
        "naive":    EXPERIMENTS_DIR / "exp1_dalle3/results/baseline_20260217_111839.json",
        "smart":    EXPERIMENTS_DIR / "exp1_dalle3/production_runs/exp1_production_20260216_193415/smart_aggregated.json",
        "manifold": EXPERIMENTS_DIR / "exp1_dalle3/results/manifold_20260216_212701.json",
    },
    "exp2_gptimage1": {
        "naive":    EXPERIMENTS_DIR / "exp2_gpt_image/results/baseline_20260217_134933.json",
        "smart":    EXPERIMENTS_DIR / "exp2_gpt_image/results/smart_control_20260217_163541.json",
        "manifold": EXPERIMENTS_DIR / "exp2_gpt_image/results/manifold_20260217_171031.json",
    },
    "exp3_extraction": {
        "naive":    EXPERIMENTS_DIR / "exp3_extraction/results/baseline_20260217_112550.json",
        "smart":    EXPERIMENTS_DIR / "exp3_extraction/results/smart_control_20260217_090513.json",
        "manifold": EXPERIMENTS_DIR / "exp3_extraction/results/manifold_20260217_085657.json",
    },
    "exp4_content": {
        "naive":    EXPERIMENTS_DIR / "exp4_content/results/baseline_20260217_134311.json",
        "smart":    EXPERIMENTS_DIR / "exp4_content/results/smart_control_20260217_140141.json",
        "manifold": EXPERIMENTS_DIR / "exp4_content/results/manifold_20260217_134342.json",
    },
}


# ── Normalized schemas ────────────────────────────────────────────────────────
@dataclass
class NormalizedTrial:
    # Identifiers
    experiment: str          # "exp1_dalle3" | "exp3_extraction"
    approach: str            # "naive" | "smart" | "manifold"
    trial_id: int

    # Outcome
    success: bool
    total_cost: float
    time_seconds: float
    timestamp: str

    # Attempt tracking (unified field name)
    attempts: int
    loop_detected: bool
    duplicate_retry: bool

    # Optional shared fields
    model: Optional[str] = None
    error: Optional[str] = None

    # EXP1-specific
    description: Optional[str] = None          # sprite description
    meets_requirements: Optional[bool] = None  # naive/manifold only

    # EXP3-specific
    complexity: Optional[str] = None           # "simple" | "medium" | "hard"
    correct_fields: Optional[int] = None
    total_fields: Optional[int] = None
    field_accuracy: Optional[float] = None
    hallucinated_fields: Optional[list] = None

    # EXP2-specific
    image_size: Optional[str] = None

    # EXP4-specific
    topic: Optional[str] = None
    word_count: Optional[int] = None
    wasted_stages: Optional[int] = None

    # Approach-specific extras (preserved verbatim, not normalised)
    metadata: dict = field(default_factory=dict)


@dataclass
class ApproachSummary:
    experiment: str
    approach: str
    source_file: str
    total_trials: int
    successful: int
    success_rate: float
    avg_attempts: float
    avg_cost: float
    avg_time_seconds: float
    loop_incidents: int
    loop_rate: float
    # EXP3 extras
    avg_field_accuracy: Optional[float] = None
    duplicate_retries: Optional[int] = None
    generated_at: str = field(default_factory=lambda: datetime.now().isoformat())


# ── Normalizers ───────────────────────────────────────────────────────────────
def normalize_exp1_trial(raw: dict, approach: str) -> NormalizedTrial:
    # EXP1/smart stores 'attempts', others store 'attempts_needed'
    attempts = raw.get("attempts", raw.get("attempts_needed", 1))

    metadata = {}
    if approach == "naive":
        metadata = {
            "duplicate_failures": raw.get("duplicate_failures", 0),
        }
    elif approach == "smart":
        metadata = {
            "validation_history": raw.get("validation_history", []),
            "adaptations": raw.get("adaptations", []),
            "duplicate_failures": raw.get("duplicate_failures", 0),
        }
    elif approach == "manifold":
        metadata = {
            "duplicate_failures": raw.get("duplicate_failures", 0),
            "total_steps_executed": raw.get("total_steps_executed"),
            "trace_length": raw.get("trace_length"),
            "spec_failures": raw.get("spec_failures", 0),
        }

    return NormalizedTrial(
        experiment="exp1_dalle3",
        approach=approach,
        trial_id=raw["trial_id"],
        success=raw["success"],
        total_cost=raw["total_cost"],
        time_seconds=raw["time_seconds"],
        timestamp=raw.get("timestamp", ""),
        attempts=attempts,
        loop_detected=raw.get("loop_detected", False),
        duplicate_retry=bool(raw.get("duplicate_failures", 0) > 0),
        model=raw.get("model"),
        error=raw.get("error"),
        description=raw.get("description"),
        meets_requirements=raw.get("meets_requirements"),
        metadata=metadata,
    )


def normalize_exp3_trial(raw: dict, approach: str) -> NormalizedTrial:
    attempts = raw.get("attempts", raw.get("attempts_needed", 1))

    # field_accuracy: some files store it directly, others we compute
    correct = raw.get("correct_fields")
    total = raw.get("total_fields", raw.get("total_expected_fields"))
    field_acc = raw.get("field_accuracy")
    if field_acc is None and correct is not None and total:
        field_acc = correct / total

    metadata = {}
    if approach == "naive":
        metadata = {
            "schema_valid": raw.get("schema_valid"),
            "all_required_fields": raw.get("all_required_fields"),
            "extracted": raw.get("extracted"),
            "expected": raw.get("expected"),
            "hallucinated_fields": raw.get("hallucinated_fields", []),
        }
    elif approach == "smart":
        metadata = {
            "validation_history": raw.get("validation_history", []),
            "context_hints_used": raw.get("context_hints_used", 0),
            "data": raw.get("data"),   # the extracted JSON output
            "email_id": raw.get("email_id"),
        }
    elif approach == "manifold":
        metadata = {
            "total_steps_executed": raw.get("total_steps_executed"),
            "trace_length": raw.get("trace_length"),
        }

    return NormalizedTrial(
        experiment="exp3_extraction",
        approach=approach,
        trial_id=raw["trial_id"],
        success=raw["success"],
        total_cost=raw["total_cost"],
        time_seconds=raw["time_seconds"],
        timestamp=raw.get("timestamp", ""),
        attempts=attempts,
        loop_detected=raw.get("loop_detected", False),
        duplicate_retry=raw.get("duplicate_retry", False),
        model=raw.get("model"),
        error=raw.get("error"),
        complexity=raw.get("complexity"),
        correct_fields=correct,
        total_fields=total,
        field_accuracy=field_acc,
        hallucinated_fields=raw.get("hallucinated_fields", []),
        metadata=metadata,
    )


def normalize_exp2_trial(raw: dict, approach: str) -> NormalizedTrial:
    attempts = raw.get("attempts", raw.get("attempts_needed", 1))
    metadata = {}
    if approach == "smart":
        metadata = {
            "validation_history": raw.get("validation_history", []),
            "adaptations": raw.get("adaptations", []),
            "duplicate_failures": raw.get("duplicate_failures", 0),
        }
    elif approach in ("naive", "manifold"):
        metadata = {
            "duplicate_failures": raw.get("duplicate_failures", 0),
            "meets_requirements": raw.get("meets_requirements"),
            "spec_failures": raw.get("spec_failures", 0),
            "total_steps_executed": raw.get("total_steps_executed"),
        }
    return NormalizedTrial(
        experiment="exp2_gptimage1",
        approach=approach,
        trial_id=raw["trial_id"],
        success=raw["success"],
        total_cost=raw["total_cost"],
        time_seconds=raw["time_seconds"],
        timestamp=raw.get("timestamp", ""),
        attempts=attempts,
        loop_detected=raw.get("loop_detected", False),
        duplicate_retry=bool(raw.get("duplicate_failures", 0) > 0),
        model=raw.get("model"),
        error=raw.get("error"),
        description=raw.get("description"),
        meets_requirements=raw.get("meets_requirements"),
        metadata=metadata,
    )


def normalize_exp4_trial(raw: dict, approach: str) -> NormalizedTrial:
    # stage_attempts can be a dict {stage: count} or an int
    sa = raw.get("stage_attempts", raw.get("attempts", 1))
    if isinstance(sa, dict):
        attempts = sum(sa.values())
    else:
        attempts = sa
    metadata = {}
    if approach == "smart":
        metadata = {
            "stage_history": raw.get("stage_history", []),
            "wasted_stages": raw.get("wasted_stages", 0),
        }
    elif approach == "naive":
        metadata = {
            "stage_history": raw.get("stage_history", []),
            "wasted_stages": raw.get("wasted_stages", 0),
        }
    elif approach == "manifold":
        metadata = {
            "total_steps_executed": raw.get("total_steps_executed"),
            "total_api_calls": raw.get("total_api_calls"),
            "total_retries": raw.get("total_retries", 0),
            "spec_failures": raw.get("spec_failures", 0),
            "trace_length": raw.get("trace_length"),
        }
    return NormalizedTrial(
        experiment="exp4_content",
        approach=approach,
        trial_id=raw["trial_id"],
        success=raw["success"],
        total_cost=raw["total_cost"],
        time_seconds=raw["time_seconds"],
        timestamp=raw.get("timestamp", ""),
        attempts=attempts,
        loop_detected=raw.get("loop_detected", False),
        duplicate_retry=False,
        model=raw.get("model"),
        error=raw.get("error"),
        complexity=raw.get("complexity"),
        topic=raw.get("topic"),
        word_count=raw.get("word_count"),
        wasted_stages=raw.get("wasted_stages", 0),
        metadata=metadata,
    )


def build_summary(trials: list[NormalizedTrial], source_file: str) -> ApproachSummary:
    total = len(trials)
    successful = sum(1 for t in trials if t.success)
    loop_incidents = sum(1 for t in trials if t.loop_detected)
    dup_retries = sum(1 for t in trials if t.duplicate_retry)
    avg_att = sum(t.attempts for t in trials) / total
    avg_cost = sum(t.total_cost for t in trials) / total
    avg_time = sum(t.time_seconds for t in trials) / total

    # EXP3 field accuracy
    fa_values = [t.field_accuracy for t in trials if t.field_accuracy is not None]
    avg_fa = sum(fa_values) / len(fa_values) if fa_values else None

    return ApproachSummary(
        experiment=trials[0].experiment,
        approach=trials[0].approach,
        source_file=source_file,
        total_trials=total,
        successful=successful,
        success_rate=successful / total,
        avg_attempts=round(avg_att, 4),
        avg_cost=round(avg_cost, 6),
        avg_time_seconds=round(avg_time, 3),
        loop_incidents=loop_incidents,
        loop_rate=round(loop_incidents / total, 4),
        avg_field_accuracy=round(avg_fa, 4) if avg_fa is not None else None,
        duplicate_retries=dup_retries,
    )


# ── Consolidation ─────────────────────────────────────────────────────────────
def consolidate_experiment(experiment: str, sources: dict) -> tuple[list, list]:
    """Returns (all_trials_as_dicts, all_summaries_as_dicts)"""
    normalizers = {
        "exp1_dalle3":    normalize_exp1_trial,
        "exp2_gptimage1": normalize_exp2_trial,
        "exp3_extraction": normalize_exp3_trial,
        "exp4_content":   normalize_exp4_trial,
    }
    normalizer = normalizers[experiment]

    all_trials = []
    all_summaries = []

    for approach, filepath in sources.items():
        raw = json.load(open(filepath, encoding='utf-8'))
        trials = [normalizer(r, approach) for r in raw["results"]]

        # Ensure trial_ids are sequential 1-50 regardless of source file format.
        # Some runs used cycling task IDs (1-5 repeated) instead of sequential run IDs.
        # Position in the results list is always authoritative.
        ids_unique = len({t.trial_id for t in trials}) == len(trials)
        if not ids_unique:
            for i, t in enumerate(trials):
                t.trial_id = i + 1

        summary = build_summary(trials, str(filepath))
        all_trials.extend(trials)
        all_summaries.append(summary)
        print(f"  {approach:<12} {len(trials)} trials  "
              f"success={summary.success_rate:.1%}  "
              f"avg_cost=${summary.avg_cost:.5f}  "
              f"source={filepath.name}")

    return [asdict(t) for t in all_trials], [asdict(s) for s in all_summaries]


def write_outputs(experiment: str, trials: list, summaries: list):
    # JSONL: one trial per line
    trials_file = DATA_OUT / f"{experiment}_trials.jsonl"
    with open(trials_file, "w", encoding='utf-8') as f:
        for t in trials:
            f.write(json.dumps(t) + "\n")

    # JSON: all summaries in one file
    summary_file = DATA_OUT / f"{experiment}_summary.json"
    with open(summary_file, "w", encoding='utf-8') as f:
        json.dump({
            "experiment": experiment,
            "generated_at": datetime.now().isoformat(),
            "total_trials": len(trials),
            "approaches": summaries,
        }, f, indent=2)

    return trials_file, summary_file


# ── Validation ────────────────────────────────────────────────────────────────
def validate(experiment: str, sources: dict, trials: list):
    """Check no data was lost or corrupted during normalization."""
    errors = []

    for approach, filepath in sources.items():
        raw = json.load(open(filepath, encoding='utf-8'))
        orig_results = raw["results"]
        norm = [t for t in trials if t["approach"] == approach]

        # Count
        if len(orig_results) != len(norm):
            errors.append(f"{approach}: count {len(orig_results)} -> {len(norm)}")

        # Success count
        orig_ok = sum(1 for r in orig_results if r["success"])
        norm_ok = sum(1 for t in norm if t["success"])
        if orig_ok != norm_ok:
            errors.append(f"{approach}: success {orig_ok} -> {norm_ok}")

        # Total cost (allow float rounding tolerance)
        orig_cost = sum(r["total_cost"] for r in orig_results)
        norm_cost = sum(t["total_cost"] for t in norm)
        if abs(orig_cost - norm_cost) > 0.0001:
            errors.append(f"{approach}: cost ${orig_cost:.4f} -> ${norm_cost:.4f}")

        # Trial IDs: must be unique and sequential 1-N after normalisation
        # (source files may have cycling IDs which are intentionally reassigned)
        norm_ids = sorted(t["trial_id"] for t in norm)
        expected_ids = list(range(1, len(norm) + 1))
        if norm_ids != expected_ids:
            errors.append(f"{approach}: normalised trial_ids not sequential: {norm_ids[:5]}")

        if not errors:
            print(f"  {approach:<12} validation OK  "
                  f"({len(norm)} trials, ${norm_cost:.4f}, {norm_ok} successful)")

    if errors:
        print("VALIDATION FAILED:")
        for e in errors:
            print(f"  ERROR: {e}")
        raise SystemExit(1)


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print(f"Output directory: {DATA_OUT}\n")

    for experiment, sources in SOURCES.items():
        print(f"{'='*60}")
        print(f"Consolidating: {experiment}")
        print(f"{'='*60}")

        trials, summaries = consolidate_experiment(experiment, sources)

        print(f"\nValidating...")
        validate(experiment, sources, trials)

        trials_file, summary_file = write_outputs(experiment, trials, summaries)
        print(f"\nWrote:")
        print(f"  {trials_file.name}  ({len(trials)} lines)")
        print(f"  {summary_file.name}")
        print()


if __name__ == "__main__":
    main()
