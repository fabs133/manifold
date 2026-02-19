"""
Experiment 2 Control: gpt-image-1 Sprite Generation (Naive Baseline)

Simple prompting approach without framework orchestration.
Direct API call with minimal retry logic — represents average developer.

Key differences from EXP1 baseline:
- Uses gpt-image-1 instead of dall-e-3
- gpt-image-1 returns b64_json (no URL), so we decode in-memory
- gpt-image-1 does NOT support response_format or quality params
"""

import os
import sys
import json
import time
import base64
import urllib.request
import urllib.error
from pathlib import Path
from typing import Dict, Any
from datetime import datetime
from io import BytesIO

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))


def generate_sprite_baseline(
    prompt_data: Dict[str, Any],
    api_key: str,
    max_retries: int = 3
) -> Dict[str, Any]:
    """
    Generate sprite using naive baseline approach.

    Args:
        prompt_data: Dict with 'description', 'frames', 'style', 'expected_grid',
                     '_trial_id' (sequential, injected by run_experiment)
        api_key: OpenAI API key
        max_retries: Maximum retry attempts

    Returns:
        Result dict with metrics
    """
    trial_id = prompt_data["_trial_id"]
    description = prompt_data["description"]
    frames = prompt_data["frames"]
    style = prompt_data["style"]
    expected_grid = prompt_data["expected_grid"]

    # Simple prompt — no sophisticated engineering
    grid_size = int(expected_grid.split('x')[0])
    prompt = f"""
Create a {grid_size}x{grid_size} grid of {frames} {description} sprites.
Each sprite should be in {style} style.
Grid layout with clear separation between sprites.
    """.strip()

    start_time = time.time()
    attempts = 0
    total_cost = 0.0
    meets_requirements = False
    loop_detected = False
    duplicate_failures = 0
    last_error = None

    for attempt in range(max_retries):
        attempts += 1

        try:
            result = call_gpt_image_1(
                prompt=prompt,
                api_key=api_key
            )

            total_cost += 0.04  # gpt-image-1 standard quality

            # Simple validation: just check we got image bytes back
            image_bytes = result.get("image_bytes")
            if image_bytes and len(image_bytes) > 10000:  # At least 10KB
                meets_requirements = True
                break
            else:
                last_error = "Empty or too-small image response"
                duplicate_failures += 1
                print(f"Attempt {attempt + 1} failed: image too small, retrying...")

        except urllib.error.HTTPError as e:
            last_error = str(e)
            print(f"Attempt {attempt + 1} HTTP error: {e}")
            if e.code == 429:
                print("Rate limit hit, waiting 60s...")
                time.sleep(60)
            else:
                time.sleep(2)
        except Exception as e:
            last_error = str(e)
            print(f"Attempt {attempt + 1} error: {e}")
            time.sleep(2)

    # Check for loops (retried with same prompt multiple times)
    if duplicate_failures >= 2:
        loop_detected = True

    elapsed = time.time() - start_time

    return {
        "trial_id": trial_id,
        "method": "control",
        "model": "gpt-image-1",
        "description": description,

        # Success metrics
        "meets_requirements": meets_requirements,
        "success": meets_requirements,

        # Efficiency metrics
        "attempts_needed": attempts,
        "total_cost": total_cost,
        "time_seconds": elapsed,

        # Loop metrics
        "loop_detected": loop_detected,
        "duplicate_failures": duplicate_failures,

        # Details
        "error": last_error if not meets_requirements else None,
        "timestamp": datetime.utcnow().isoformat()
    }


def call_gpt_image_1(prompt: str, api_key: str) -> Dict[str, Any]:
    """
    Call gpt-image-1 API.

    Returns dict with 'image_bytes' (raw PNG bytes).

    Notes:
    - gpt-image-1 does NOT support response_format or quality params
    - Returns b64_json (not URL) — decoded to bytes here
    """
    url = "https://api.openai.com/v1/images/generations"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    # gpt-image-1: no response_format, no quality param
    payload = {
        "model": "gpt-image-1",
        "prompt": prompt,
        "n": 1,
        "size": "1024x1024",
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode('utf-8'),
        headers=headers,
        method='POST'
    )

    with urllib.request.urlopen(req, timeout=120) as response:
        result = json.loads(response.read().decode('utf-8'))

    # gpt-image-1 returns b64_json, not URL
    b64_data = result["data"][0]["b64_json"]
    image_bytes = base64.b64decode(b64_data)

    return {"image_bytes": image_bytes}


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
    dataset_path = Path(__file__).resolve().parent.parent.parent / "datasets" / "sprite_prompts.json"
    with open(dataset_path) as f:
        prompts = json.load(f)

    print(f"\n{'='*60}")
    print("NAIVE BASELINE: gpt-image-1 Sprite Generation")
    print(f"{'='*60}")
    print(f"Trials: {num_trials}")
    print(f"Dataset: {len(prompts)} prompts (cycling)")
    print()

    results = []
    for i in range(num_trials):
        prompt_data = prompts[i % len(prompts)].copy()
        prompt_data["_trial_id"] = i + 1  # sequential IDs 1..num_trials
        print(f"\n=== Trial {i+1}/{num_trials}: {prompt_data['description']} (task {prompt_data['id']}) ===")

        result = generate_sprite_baseline(prompt_data, api_key)
        results.append(result)

        print(f"Success: {result['success']}")
        print(f"Attempts: {result['attempts_needed']}")
        print(f"Cost: ${result['total_cost']:.4f}")
        print(f"Time: {result['time_seconds']:.2f}s")
        if result.get('loop_detected'):
            print("WARNING: LOOP DETECTED")

        # Progress summary
        successes = sum(1 for r in results if r["success"])
        print(f"Running: {successes}/{len(results)} ({successes/len(results)*100:.1f}%) successful")

        # Rate limit: gpt-image-1 Tier 3 ~7 img/min
        # 10s delay = 6 img/min, stays under the limit
        if i < num_trials - 1:
            time.sleep(10)

    # Save results — absolute path based on __file__ so it works from any CWD
    output_path = Path(__file__).resolve().parent.parent / "results" / f"baseline_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w') as f:
        json.dump({
            "experiment": "exp2_gptimage1_control",
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
    avg_attempts = sum(r["attempts_needed"] for r in results) / total
    avg_cost = sum(r["total_cost"] for r in results) / total
    avg_time = sum(r["time_seconds"] for r in results) / total
    loops = sum(1 for r in results if r.get("loop_detected"))

    return {
        "total_trials": total,
        "successful": successful,
        "success_rate": successful / total,
        "avg_attempts": avg_attempts,
        "avg_cost_per_trial": avg_cost,
        "avg_time_seconds": avg_time,
        "loop_incidents": loops,
        "loop_rate": loops / total
    }


def print_summary(results: list):
    """Print summary statistics."""
    summary = calculate_summary(results)

    print("\n" + "="*60)
    print("NAIVE BASELINE SUMMARY (gpt-image-1)")
    print("="*60)
    print(f"Total Trials:     {summary['total_trials']}")
    print(f"Successful:       {summary['successful']} ({summary['success_rate']:.1%})")
    print(f"Avg Attempts:     {summary['avg_attempts']:.2f}")
    print(f"Avg Cost:         ${summary['avg_cost_per_trial']:.4f}")
    print(f"Avg Time:         {summary['avg_time_seconds']:.2f}s")
    print(f"Loop Incidents:   {summary['loop_incidents']} ({summary['loop_rate']:.1%})")
    print("="*60)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Exp2 Naive Baseline: gpt-image-1 Sprite Generation")
    parser.add_argument("--trials", type=int, default=5, help="Number of trials to run")
    args = parser.parse_args()

    run_experiment(num_trials=args.trials)
