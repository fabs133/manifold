"""
Experiment 4 Control: Multi-Step Content Generation (Naive Baseline)

Simple 4-stage pipeline: Research → Outline → Draft → Polish.
No validation between stages, no retry logic, no spec contracts.
Represents how most developers would build a basic content pipeline.

Intentional limitations (for fair comparison):
- No per-stage validation
- If a stage produces poor output, pipeline continues anyway
- No retry on failure
- No loop detection
"""

import os
import sys
import json
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))


def call_gpt4o(
    system_msg: str,
    user_msg: str,
    api_key: str,
    temperature: float = 0.5,
    max_tokens: int = 3000
) -> Dict[str, Any]:
    """
    Call GPT-4o API.

    Returns dict with 'output' (str), 'cost' (float), 'usage' (dict).
    """
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "gpt-4o",
        "messages": [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg}
        ],
        "temperature": temperature,
        "max_tokens": max_tokens
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode('utf-8'),
        headers=headers,
        method='POST'
    )

    with urllib.request.urlopen(req, timeout=120) as response:
        result = json.loads(response.read().decode('utf-8'))

    message = result["choices"][0]["message"]["content"]
    usage = result.get("usage", {})

    # GPT-4o pricing: $2.50/1M input, $10.00/1M output
    prompt_tokens = usage.get("prompt_tokens", 0)
    completion_tokens = usage.get("completion_tokens", 0)
    cost = (prompt_tokens / 1_000_000) * 2.50 + (completion_tokens / 1_000_000) * 10.00

    return {
        "output": message,
        "cost": cost,
        "usage": usage
    }


def generate_content_baseline(
    topic_data: Dict[str, Any],
    api_key: str
) -> Dict[str, Any]:
    """
    Generate content using naive 4-stage pipeline.

    No validation between stages. If any stage fails or produces
    poor output, the pipeline just continues with what it has.

    Returns result dict with metrics.
    """
    trial_id = topic_data["_trial_id"]
    topic = topic_data["topic"]
    complexity = topic_data["complexity"]

    start_time = time.time()
    total_cost = 0.0
    stage_attempts = {}
    stage_history = []
    success = False
    final_content = None
    word_count = 0

    print(f"\n{'='*60}")
    print(f"NAIVE BASELINE: {topic}")
    print(f"{'='*60}")

    # Stage 1: Research
    print("\n[Stage 1] Research")
    try:
        r1 = call_gpt4o(
            system_msg="You are a research assistant. Gather 3-5 key points about the topic.",
            user_msg=f"Research key points for article about: {topic}",
            api_key=api_key,
            temperature=0.7
        )
        research = r1["output"]
        total_cost += r1["cost"]
        stage_attempts["research"] = 1
        stage_history.append({"stage": "research", "success": True, "cost": r1["cost"]})
        print(f"  Done (cost: ${r1['cost']:.4f})")
    except Exception as e:
        print(f"  FAILED: {e}")
        stage_history.append({"stage": "research", "success": False, "error": str(e)})
        elapsed = time.time() - start_time
        return _make_result(trial_id, topic, complexity, False, None, 0,
                            total_cost, elapsed, stage_attempts, stage_history)

    # Stage 2: Outline
    print("\n[Stage 2] Outline")
    try:
        r2 = call_gpt4o(
            system_msg="You are an outlining expert. Create a structured article outline with ## headers.",
            user_msg=f"Create outline for article.\n\nTopic: {topic}\n\nResearch:\n{research}\n\nFormat with ## headers.",
            api_key=api_key,
            temperature=0.5
        )
        outline = r2["output"]
        total_cost += r2["cost"]
        stage_attempts["outline"] = 1
        stage_history.append({"stage": "outline", "success": True, "cost": r2["cost"]})
        print(f"  Done (cost: ${r2['cost']:.4f})")
    except Exception as e:
        print(f"  FAILED: {e}")
        stage_history.append({"stage": "outline", "success": False, "error": str(e)})
        elapsed = time.time() - start_time
        return _make_result(trial_id, topic, complexity, False, None, 0,
                            total_cost, elapsed, stage_attempts, stage_history)

    # Stage 3: Draft
    print("\n[Stage 3] Draft")
    try:
        r3 = call_gpt4o(
            system_msg="You are a technical writer. Write a complete article following the outline.",
            user_msg=f"Write article following this outline:\n\n{outline}\n\nTopic: {topic}\nWrite complete article.",
            api_key=api_key,
            temperature=0.6,
            max_tokens=3000
        )
        draft = r3["output"]
        total_cost += r3["cost"]
        stage_attempts["draft"] = 1
        stage_history.append({"stage": "draft", "success": True, "cost": r3["cost"],
                               "word_count": len(draft.split())})
        print(f"  Done ({len(draft.split())} words, cost: ${r3['cost']:.4f})")
    except Exception as e:
        print(f"  FAILED: {e}")
        stage_history.append({"stage": "draft", "success": False, "error": str(e)})
        elapsed = time.time() - start_time
        return _make_result(trial_id, topic, complexity, False, None, 0,
                            total_cost, elapsed, stage_attempts, stage_history)

    # Stage 4: Polish
    print("\n[Stage 4] Polish")
    try:
        r4 = call_gpt4o(
            system_msg="You are an editor. Polish the article for publication.",
            user_msg=f"Polish this article for publication:\n\n{draft}\n\nFix grammar, improve clarity, maintain length.",
            api_key=api_key,
            temperature=0.3,
            max_tokens=3000
        )
        final_content = r4["output"]
        total_cost += r4["cost"]
        word_count = len(final_content.split())
        stage_attempts["polish"] = 1
        stage_history.append({"stage": "polish", "success": True, "cost": r4["cost"],
                               "word_count": word_count})
        print(f"  Done ({word_count} words, cost: ${r4['cost']:.4f})")
        success = True
    except Exception as e:
        print(f"  FAILED: {e}")
        stage_history.append({"stage": "polish", "success": False, "error": str(e)})
        elapsed = time.time() - start_time
        return _make_result(trial_id, topic, complexity, False, None, 0,
                            total_cost, elapsed, stage_attempts, stage_history)

    elapsed = time.time() - start_time
    print(f"\nDone in {elapsed:.1f}s — {word_count} words — ${total_cost:.4f}")
    return _make_result(trial_id, topic, complexity, success, final_content, word_count,
                        total_cost, elapsed, stage_attempts, stage_history)


def _make_result(trial_id, topic, complexity, success, final_content, word_count,
                 total_cost, elapsed, stage_attempts, stage_history) -> Dict[str, Any]:
    """Helper: build result dict."""
    return {
        "trial_id": trial_id,
        "topic": topic,
        "complexity": complexity,
        "method": "control",
        "model": "gpt-4o",

        # Success metrics
        "success": success,
        "word_count": word_count,

        # Efficiency
        "total_cost": total_cost,
        "time_seconds": elapsed,
        "stage_attempts": stage_attempts,

        # Pipeline metrics
        "wasted_stages": 0,  # naive doesn't track this

        # Content (excluded from JSON to save space)
        # "final_content": final_content,

        # Stage trace
        "stage_history": stage_history,

        "timestamp": datetime.utcnow().isoformat()
    }


def run_experiment(num_trials: int = 5):
    """Run the naive baseline experiment."""
    # Load .env from experiments root
    env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY environment variable required")

    # Load dataset
    dataset_path = Path(__file__).resolve().parent.parent.parent / "datasets" / "content_topics.json"
    with open(dataset_path) as f:
        topics = json.load(f)

    print(f"\n{'='*60}")
    print("NAIVE BASELINE: Multi-Step Content Generation")
    print(f"{'='*60}")
    print(f"Trials: {num_trials}")
    print(f"Dataset: {len(topics)} topics (cycling)")
    print()

    results = []
    for i in range(num_trials):
        topic_data = topics[i % len(topics)].copy()
        topic_data["_trial_id"] = i + 1  # sequential IDs 1..num_trials
        print(f"\n{'====='*12}")
        print(f"TRIAL {i+1}/{num_trials} | {topic_data['complexity'].upper()}")
        print(f"Topic: {topic_data['topic']} (task {topic_data['id']})")
        print(f"{'====='*12}")

        result = generate_content_baseline(topic_data, api_key)
        results.append(result)

        # Progress summary
        successes = sum(1 for r in results if r["success"])
        avg_cost = sum(r["total_cost"] for r in results) / len(results)
        print(f"\nProgress: {successes}/{len(results)} ({successes/len(results)*100:.1f}%) | Avg cost: ${avg_cost:.3f}")

        # Rate limit: 3s between trials (GPT-4o Tier 3 handles bursts well,
        # but 4 sequential calls per trial can spike TPM on fast topics)
        if i < num_trials - 1:
            time.sleep(3)

    # Save results — absolute path based on __file__
    output_path = Path(__file__).resolve().parent.parent / "results" / f"baseline_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w') as f:
        json.dump({
            "experiment": "exp4_content_control",
            "trials": num_trials,
            "results": results,
            "summary": calculate_summary(results)
        }, f, indent=2)

    print(f"\n[OK] Results saved to: {output_path}")
    print_summary(results)


def calculate_summary(results: list) -> Dict[str, Any]:
    """Calculate aggregate statistics."""
    total = len(results)
    successful = sum(1 for r in results if r["success"])
    avg_cost = sum(r["total_cost"] for r in results) / total if total > 0 else 0
    avg_time = sum(r["time_seconds"] for r in results) / total if total > 0 else 0
    avg_words = (
        sum(r["word_count"] for r in results if r["success"]) /
        max(sum(1 for r in results if r["success"]), 1)
    )
    avg_stages = sum(sum(r["stage_attempts"].values()) for r in results) / total if total > 0 else 0

    return {
        "total_trials": total,
        "successful": successful,
        "success_rate": successful / total if total > 0 else 0,
        "avg_cost_per_trial": avg_cost,
        "avg_time_seconds": avg_time,
        "avg_word_count": avg_words,
        "avg_total_stages": avg_stages
    }


def print_summary(results: list):
    """Print summary statistics."""
    summary = calculate_summary(results)

    print("\n" + "="*60)
    print("NAIVE BASELINE SUMMARY (Content Generation)")
    print("="*60)
    print(f"Total Trials:     {summary['total_trials']}")
    print(f"Successful:       {summary['successful']} ({summary['success_rate']:.1%})")
    print(f"Avg Cost:         ${summary['avg_cost_per_trial']:.4f}")
    print(f"Avg Time:         {summary['avg_time_seconds']:.2f}s")
    print(f"Avg Word Count:   {summary['avg_word_count']:.0f}")
    print(f"Avg Total Stages: {summary['avg_total_stages']:.2f}")
    print("="*60)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Exp4 Naive Baseline: Multi-Step Content Generation")
    parser.add_argument("--trials", type=int, default=5, help="Number of trials to run")
    args = parser.parse_args()

    run_experiment(num_trials=args.trials)
