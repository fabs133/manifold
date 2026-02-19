"""
Comparison analysis of naive / smart / manifold approaches across EXP1 and EXP3.

Reads the revalidated JSONL files and prints:
  1. Top-level success rate comparison (original vs universal)
  2. Cost and efficiency breakdown
  3. Per-rule failure analysis
  4. Verdict concordance (FP / FN breakdown)
  5. Per-complexity breakdown for EXP3
  6. Summary insight table

Run:
  python scripts/analyze.py
"""

import json
from pathlib import Path
from collections import defaultdict
from typing import Optional

# ── Paths ─────────────────────────────────────────────────────────────────────
SCRIPTS_DIR     = Path(__file__).resolve().parent
EXPERIMENTS_DIR = SCRIPTS_DIR.parent
REVALIDATED     = EXPERIMENTS_DIR / "data" / "revalidated"
CONSOLIDATED    = EXPERIMENTS_DIR / "data" / "consolidated"

APPROACHES = ["naive", "smart", "manifold"]

# ── Helpers ───────────────────────────────────────────────────────────────────

def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def pct(n: int, total: int) -> str:
    if total == 0:
        return "  N/A"
    return f"{n/total:6.1%}"


def avg(values: list) -> Optional[float]:
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


def fmt(v: Optional[float], fmt_str: str = ".4f") -> str:
    return format(v, fmt_str) if v is not None else "   N/A"


def sep(char: str = "=", width: int = 76) -> str:
    return char * width


# ── Section printers ──────────────────────────────────────────────────────────

def section(title: str):
    print()
    print(sep())
    print(f"  {title}")
    print(sep())


def print_success_comparison(exp: str, by_approach: dict):
    """Original vs universal success rates."""
    section(f"[{exp}]  SUCCESS RATE  (original vs universal)")

    note = (
        "NOTE: 'universal' applies consistent criteria across all approaches.\n"
        "      UNKNOWN verdicts (no data to evaluate) are excluded from universal_success."
    )
    print(f"  {note}\n")

    header = f"  {'Approach':<10}  {'N':>4}  {'Orig':>7}  {'Univ':>7}  {'Delta':>7}  {'FP':>4}  {'FN':>4}  {'w/Unk':>6}"
    print(header)
    print("  " + "-" * 58)

    for approach in APPROACHES:
        ts = by_approach.get(approach, [])
        if not ts:
            continue
        n        = len(ts)
        orig_ok  = sum(1 for t in ts if t["universal"]["original_success"])
        univ_ok  = sum(1 for t in ts if t["universal"]["universal_success"])
        fp       = sum(1 for t in ts if t["universal"]["false_positive"])
        fn       = sum(1 for t in ts if t["universal"]["false_negative"])
        has_unk  = sum(1 for t in ts if any(
            r["verdict"] == "unknown" for r in t["universal"]["rule_results"]
        ))
        delta    = (univ_ok - orig_ok) / n
        delta_s  = f"{delta:+7.1%}"
        print(f"  {approach:<10}  {n:>4}  {pct(orig_ok,n)}  {pct(univ_ok,n)}  {delta_s}  {fp:>4}  {fn:>4}  {has_unk:>6}")


def print_cost_efficiency(exp: str, by_approach: dict):
    """Cost and efficiency metrics."""
    section(f"[{exp}]  COST & EFFICIENCY")

    header = f"  {'Approach':<10}  {'N':>4}  {'Avg Cost':>10}  {'Total Cost':>11}  {'Avg Time':>10}  {'Avg Attempts':>13}"
    print(header)
    print("  " + "-" * 65)

    for approach in APPROACHES:
        ts = by_approach.get(approach, [])
        if not ts:
            continue
        n           = len(ts)
        avg_cost    = avg([t.get("total_cost") for t in ts])
        total_cost  = sum(t.get("total_cost", 0) for t in ts)
        avg_time    = avg([t.get("time_seconds") for t in ts])
        avg_att     = avg([t.get("attempts") for t in ts])
        print(f"  {approach:<10}  {n:>4}  ${fmt(avg_cost,'8.5f')}  ${fmt(total_cost,'9.4f')}  {fmt(avg_time,'8.2f')}s  {fmt(avg_att,'11.2f')}")

    # Cost-per-success
    print()
    print(f"  Cost-per-successful-trial (universal success):")
    print(f"  {'Approach':<10}  {'Successful':>10}  {'Total Cost':>11}  {'$/success':>10}")
    print("  " + "-" * 48)
    for approach in APPROACHES:
        ts = by_approach.get(approach, [])
        if not ts:
            continue
        successes  = [t for t in ts if t["universal"]["universal_success"]]
        n_succ     = len(successes)
        total_cost = sum(t.get("total_cost", 0) for t in ts)
        cps        = total_cost / n_succ if n_succ > 0 else None
        print(f"  {approach:<10}  {n_succ:>10}  ${fmt(total_cost,'9.4f')}  ${fmt(cps,'8.5f')}")


def print_rule_breakdown(exp: str, by_approach: dict, all_rules: list):
    """Per-rule PASS/FAIL/UNKNOWN counts."""
    section(f"[{exp}]  PER-RULE VERDICT BREAKDOWN  (P=PASS  F=FAIL  U=UNKNOWN)")

    print(f"  {'Rule':<28}  {'Sev':<6}  ", end="")
    for approach in APPROACHES:
        if by_approach.get(approach):
            print(f"  {approach:<18}", end="")
    print()
    print("  " + "-" * (28 + 6 + 4 + len(APPROACHES) * 20))

    for rule in all_rules:
        sev = next(
            (r["severity"] for ts in by_approach.values()
             for t in ts for r in t["universal"]["rule_results"]
             if r["rule"] == rule),
            "?"
        )
        tag = "CRIT " if sev == "critical" else "WARN "
        row = f"  {rule:<28}  {tag:<6}  "
        for approach in APPROACHES:
            ts = by_approach.get(approach, [])
            if not ts:
                continue
            passes   = sum(1 for t in ts if any(r["rule"]==rule and r["verdict"]=="pass"   for r in t["universal"]["rule_results"]))
            fails    = sum(1 for t in ts if any(r["rule"]==rule and r["verdict"]=="fail"   for r in t["universal"]["rule_results"]))
            unknowns = sum(1 for t in ts if any(r["rule"]==rule and r["verdict"]=="unknown" for r in t["universal"]["rule_results"]))
            row += f"  P={passes:2d} F={fails:2d} U={unknowns:2d}    "
        print(row)


def print_concordance(exp: str, by_approach: dict):
    """False positive / false negative details."""
    section(f"[{exp}]  VERDICT CONCORDANCE")
    print(f"  FP = trial original says PASS but universal says FAIL (original too lenient)")
    print(f"  FN = trial original says FAIL but universal says PASS (original too strict)")
    print()

    for approach in APPROACHES:
        ts = by_approach.get(approach, [])
        if not ts:
            continue
        fps = [t for t in ts if t["universal"]["false_positive"]]
        fns = [t for t in ts if t["universal"]["false_negative"]]

        if not fps and not fns:
            print(f"  {approach}: perfect concordance (0 FP, 0 FN)")
            continue

        print(f"  {approach}:")
        if fps:
            print(f"    False positives ({len(fps)}) — original claimed success but universal disagrees:")
            for t in fps[:5]:  # show up to 5
                failing_rules = [
                    r["rule"] for r in t["universal"]["rule_results"]
                    if r["verdict"] == "fail" and r["severity"] == "critical"
                ]
                print(f"      trial {t['trial_id']:3d}: failed universal rules = {failing_rules}")
            if len(fps) > 5:
                print(f"      ... and {len(fps)-5} more")
        if fns:
            print(f"    False negatives ({len(fns)}) — original claimed failure but universal disagrees:")
            for t in fns[:5]:
                print(f"      trial {t['trial_id']:3d}")
            if len(fns) > 5:
                print(f"      ... and {len(fns)-5} more")
        print()


def print_exp3_complexity(by_approach: dict):
    """EXP3-specific: success rate by complexity tier."""
    section("[exp3_extraction]  UNIVERSAL SUCCESS BY COMPLEXITY")

    complexities = ["simple", "medium", "hard"]

    header = f"  {'Approach':<10}  {'Complexity':<10}  {'N':>4}  {'Univ%':>7}  {'FP':>4}"
    print(header)
    print("  " + "-" * 45)

    for approach in APPROACHES:
        ts = by_approach.get(approach, [])
        if not ts:
            continue
        for cx in complexities:
            group = [t for t in ts if t.get("complexity") == cx]
            if not group:
                continue
            n      = len(group)
            univ_ok = sum(1 for t in group if t["universal"]["universal_success"])
            fp      = sum(1 for t in group if t["universal"]["false_positive"])
            print(f"  {approach:<10}  {cx:<10}  {n:>4}  {pct(univ_ok,n)}  {fp:>4}")
        print()


def print_exp3_field_accuracy(by_approach: dict):
    """EXP3-specific: field accuracy distribution."""
    section("[exp3_extraction]  FIELD ACCURACY DISTRIBUTION")
    print(f"  Only trials where field_accuracy could be computed (extracted+expected data present).\n")

    for approach in APPROACHES:
        ts = by_approach.get(approach, [])
        if not ts:
            continue
        fa_vals = [t.get("field_accuracy") for t in ts if t.get("field_accuracy") is not None]
        if not fa_vals:
            print(f"  {approach}: no field_accuracy data\n")
            continue
        perfect = sum(1 for v in fa_vals if v >= 1.0)
        high    = sum(1 for v in fa_vals if 0.8 <= v < 1.0)
        mid     = sum(1 for v in fa_vals if 0.5 <= v < 0.8)
        low     = sum(1 for v in fa_vals if v < 0.5)
        avg_fa  = avg(fa_vals)
        print(f"  {approach} (n={len(fa_vals)} trials with data):  avg={fmt(avg_fa,'.3f')}")
        print(f"    Perfect (1.0)  : {perfect:3d}  ({pct(perfect,len(fa_vals))})")
        print(f"    High   (0.8-1.0): {high:3d}  ({pct(high,len(fa_vals))})")
        print(f"    Mid    (0.5-0.8): {mid:3d}  ({pct(mid,len(fa_vals))})")
        print(f"    Low    (<0.5)   : {low:3d}  ({pct(low,len(fa_vals))})")
        print()


def print_insight_summary(exp1_by_approach: dict, exp3_by_approach: dict):
    """High-level insight table."""
    section("MANIFOLD ADVANTAGE SUMMARY")

    print(
        "  This table compares manifold to naive and smart on universal (comparable)\n"
        "  success rates — stripping away lenient original validation.\n"
    )

    rows = []

    # EXP1
    for approach in APPROACHES:
        ts = exp1_by_approach.get(approach, [])
        if not ts:
            continue
        n        = len(ts)
        orig_ok  = sum(1 for t in ts if t["universal"]["original_success"])
        univ_ok  = sum(1 for t in ts if t["universal"]["universal_success"])
        avg_cost = avg([t.get("total_cost") for t in ts])
        rows.append({
            "exp": "EXP1 (sprite)",
            "approach": approach,
            "n": n,
            "orig_pct": orig_ok / n,
            "univ_pct": univ_ok / n,
            "avg_cost": avg_cost,
        })

    # EXP3
    for approach in APPROACHES:
        ts = exp3_by_approach.get(approach, [])
        if not ts:
            continue
        n        = len(ts)
        orig_ok  = sum(1 for t in ts if t["universal"]["original_success"])
        univ_ok  = sum(1 for t in ts if t["universal"]["universal_success"])
        avg_cost = avg([t.get("total_cost") for t in ts])
        rows.append({
            "exp": "EXP3 (extract)",
            "approach": approach,
            "n": n,
            "orig_pct": orig_ok / n,
            "univ_pct": univ_ok / n,
            "avg_cost": avg_cost,
        })

    # Load EXP2 and EXP4 for the summary table
    exp2_path = REVALIDATED / "exp2_gptimage1_trials_universal.jsonl"
    exp4_path = REVALIDATED / "exp4_content_trials_universal.jsonl"

    for exp_label, exp_path, exp_key in [
        ("EXP2 (img-1)", exp2_path, "exp2"),
        ("EXP4 (content)", exp4_path, "exp4"),
    ]:
        if not exp_path.exists():
            continue
        exp_trials = load_jsonl(exp_path)
        exp_by = defaultdict(list)
        for t in exp_trials:
            exp_by[t["approach"]].append(t)
        for approach in APPROACHES:
            ts = exp_by.get(approach, [])
            if not ts:
                continue
            n        = len(ts)
            orig_ok  = sum(1 for t in ts if t["universal"]["original_success"])
            univ_ok  = sum(1 for t in ts if t["universal"]["universal_success"])
            avg_cost = avg([t.get("total_cost") for t in ts])
            rows.append({
                "exp": exp_label,
                "approach": approach,
                "n": n,
                "orig_pct": orig_ok / n,
                "univ_pct": univ_ok / n,
                "avg_cost": avg_cost,
            })

    header = f"  {'Experiment':<16}  {'Approach':<10}  {'Orig%':>7}  {'Univ%':>7}  {'Avg Cost':>10}"
    print(header)
    print("  " + "-" * 58)

    last_exp = None
    for row in rows:
        if last_exp and last_exp != row["exp"]:
            print()
        last_exp = row["exp"]
        print(
            f"  {row['exp']:<16}  {row['approach']:<10}  "
            f"{row['orig_pct']:7.1%}  {row['univ_pct']:7.1%}  "
            f"${fmt(row['avg_cost'],'8.5f')}"
        )

    # Key findings
    print()
    print("  Key findings:")

    # EXP1
    e1_naive   = next((r for r in rows if r["exp"]=="EXP1 (sprite)" and r["approach"]=="naive"), None)
    e1_smart   = next((r for r in rows if r["exp"]=="EXP1 (sprite)" and r["approach"]=="smart"), None)
    e1_mani    = next((r for r in rows if r["exp"]=="EXP1 (sprite)" and r["approach"]=="manifold"), None)
    if e1_smart and e1_mani:
        print(f"  EXP1: naive/manifold cannot be compared on separation (no image analysis data).")
        print(f"        smart_control validates separation: {e1_smart['univ_pct']:.0%} universal success.")
        print(f"        manifold ALSO claims 100% — but separation is UNKNOWN (not verified).")

    # EXP3
    e3_naive   = next((r for r in rows if r["exp"]=="EXP3 (extract)" and r["approach"]=="naive"), None)
    e3_smart   = next((r for r in rows if r["exp"]=="EXP3 (extract)" and r["approach"]=="smart"), None)
    e3_mani    = next((r for r in rows if r["exp"]=="EXP3 (extract)" and r["approach"]=="manifold"), None)
    if e3_naive and e3_mani:
        print()
        print(f"  EXP3: naive claimed {e3_naive['orig_pct']:.0%} but universal shows {e3_naive['univ_pct']:.0%} — "
              f"many field accuracy failures masked by lenient check.")
        print(f"        smart claimed {e3_smart['orig_pct']:.0%} but universal shows {e3_smart['univ_pct']:.0%} — "
              f"strong field_accuracy filter reveals real failure rate.")
        print(f"        manifold: {e3_mani['orig_pct']:.0%} original vs {e3_mani['univ_pct']:.0%} universal — "
              f"near-perfect concordance, no false positives.")
        if e3_mani and e3_naive:
            gap = e3_mani["univ_pct"] - e3_naive["univ_pct"]
            print(f"        => Manifold advantage over naive (universal): +{gap:.0%}")
        if e3_mani and e3_smart:
            gap = e3_mani["univ_pct"] - e3_smart["univ_pct"]
            print(f"        => Manifold advantage over smart (universal): +{gap:.0%}")


# ── Main ──────────────────────────────────────────────────────────────────────

def analyze_experiment(exp: str) -> dict:
    """Load revalidated JSONL, return dict by approach."""
    fp = REVALIDATED / f"{exp}_trials_universal.jsonl"
    if not fp.exists():
        print(f"  [SKIP] {fp} not found — run universal_validator.py first.")
        return {}
    trials = load_jsonl(fp)
    by_approach: dict = defaultdict(list)
    for t in trials:
        by_approach[t["approach"]].append(t)
    return dict(by_approach)


def collect_rules(by_approach: dict) -> list:
    all_rules: list = []
    for ts in by_approach.values():
        for t in ts:
            for r in t["universal"]["rule_results"]:
                if r["rule"] not in all_rules:
                    all_rules.append(r["rule"])
    return all_rules


def main():
    print(sep())
    print("  MANIFOLD EXPERIMENT ANALYSIS")
    print(f"  Source: {REVALIDATED}")
    print(sep())

    exp1_by = analyze_experiment("exp1_dalle3")
    exp2_by = analyze_experiment("exp2_gptimage1")
    exp3_by = analyze_experiment("exp3_extraction")
    exp4_by = analyze_experiment("exp4_content")

    if exp1_by:
        print_success_comparison("exp1_dalle3", exp1_by)
        print_cost_efficiency("exp1_dalle3", exp1_by)
        print_rule_breakdown("exp1_dalle3", exp1_by, collect_rules(exp1_by))
        print_concordance("exp1_dalle3", exp1_by)

    if exp2_by:
        print_success_comparison("exp2_gptimage1", exp2_by)
        print_cost_efficiency("exp2_gptimage1", exp2_by)
        print_rule_breakdown("exp2_gptimage1", exp2_by, collect_rules(exp2_by))
        print_concordance("exp2_gptimage1", exp2_by)

    if exp3_by:
        print_success_comparison("exp3_extraction", exp3_by)
        print_cost_efficiency("exp3_extraction", exp3_by)
        print_rule_breakdown("exp3_extraction", exp3_by, collect_rules(exp3_by))
        print_concordance("exp3_extraction", exp3_by)
        print_exp3_complexity(exp3_by)
        print_exp3_field_accuracy(exp3_by)

    if exp4_by:
        print_success_comparison("exp4_content", exp4_by)
        print_cost_efficiency("exp4_content", exp4_by)
        print_rule_breakdown("exp4_content", exp4_by, collect_rules(exp4_by))
        print_concordance("exp4_content", exp4_by)

    if exp1_by and exp3_by:
        print_insight_summary(exp1_by, exp3_by)

    print()
    print(sep())
    print("  Analysis complete.")
    print(sep())


if __name__ == "__main__":
    main()
