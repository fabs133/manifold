"""
Experiment 1 Control: DALL-E 3 Sprite Generation (Baseline)

This is the "normal prompting" approach without Manifold orchestration.
Represents how most developers would solve this problem.
"""

import os
import sys
import json
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Dict, Any
from datetime import datetime

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))


def generate_sprite_baseline(
    prompt_data: Dict[str, Any],
    api_key: str,
    max_retries: int = 3
) -> Dict[str, Any]:
    """
    Generate sprite using baseline approach (manual retries).

    Args:
        prompt_data: Dict with 'description', 'frames', 'style', 'expected_grid'
        api_key: OpenAI API key
        max_retries: Maximum retry attempts

    Returns:
        Result dict with metrics
    """
    trial_id = prompt_data["_trial_id"]  # sequential ID assigned by run_experiment
    description = prompt_data["description"]
    frames = prompt_data["frames"]
    style = prompt_data["style"]
    expected_grid = prompt_data["expected_grid"]

    # Build prompt (simple approach - no sophisticated prompt engineering)
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

    # Simple retry loop
    for attempt in range(max_retries):
        attempts += 1

        try:
            # Make API call
            result = call_openai_images_api(
                prompt=prompt,
                model="dall-e-3",
                size="1024x1024",
                quality="standard",
                api_key=api_key
            )

            # Estimate cost
            cost = 0.04  # DALL-E 3 standard quality
            total_cost += cost

            # Simple validation (no sophisticated checking)
            image_url = result.get("url")
            if image_url and validate_basic(image_url):
                meets_requirements = True
                break
            else:
                last_error = "Validation failed"
                duplicate_failures += 1
                print(f"Attempt {attempt + 1} failed validation, retrying...")

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
            time.sleep(2)  # Simple backoff

    # Check for loops (if retried with same prompt multiple times)
    if duplicate_failures >= 2:
        loop_detected = True

    elapsed = time.time() - start_time

    return {
        "trial_id": trial_id,
        "method": "control",
        "model": "dall-e-3",
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


def call_openai_images_api(
    prompt: str,
    model: str,
    size: str,
    quality: str,
    api_key: str
) -> Dict[str, Any]:
    """Call OpenAI Images API."""
    url = "https://api.openai.com/v1/images/generations"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": model,
        "prompt": prompt,
        "n": 1,
        "size": size,
        "quality": quality,
        "response_format": "url"
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode('utf-8'),
        headers=headers,
        method='POST'
    )

    with urllib.request.urlopen(req, timeout=120) as response:
        result = json.loads(response.read().decode('utf-8'))

    return result["data"][0]


def validate_basic(image_url: str) -> bool:
    """
    Basic validation - just checks if image exists and is right size.

    In real baseline, most developers wouldn't even do this much validation.
    """
    try:
        req = urllib.request.Request(image_url)
        with urllib.request.urlopen(req, timeout=30) as response:
            # Just check that we got data
            data = response.read()
            return len(data) > 10000  # At least 10KB

    except Exception:
        return False


def run_experiment(num_trials: int = 5):
    """Run the baseline experiment."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY environment variable required")

    # Load dataset
    dataset_path = Path(__file__).parent.parent.parent / "datasets" / "sprite_prompts.json"
    with open(dataset_path) as f:
        prompts = json.load(f)

    # Run trials
    results = []
    for i in range(num_trials):
        prompt_data = prompts[i % len(prompts)].copy()
        prompt_data["_trial_id"] = i + 1  # sequential across all repetitions
        print(f"\n=== Trial {i+1}/{num_trials}: {prompt_data['description']} (task {prompt_data['id']}) ===")

        result = generate_sprite_baseline(prompt_data, api_key)
        results.append(result)

        print(f"Success: {result['success']}")
        print(f"Attempts: {result['attempts_needed']}")
        print(f"Cost: ${result['total_cost']:.4f}")
        print(f"Time: {result['time_seconds']:.2f}s")
        if result.get('loop_detected'):
            print("⚠️  LOOP DETECTED")

        # Rate limit guard: DALL-E 3 allows 5 req/min → wait 13s between trials
        if i < num_trials - 1:
            time.sleep(13)

    # Save results (absolute path based on __file__ so it works from any working directory)
    output_path = Path(__file__).resolve().parent.parent / "results" / f"baseline_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w') as f:
        json.dump({
            "experiment": "exp1_dalle3_control",
            "trials": num_trials,
            "results": results,
            "summary": calculate_summary(results)
        }, f, indent=2)

    print(f"\n✅ Results saved to: {output_path}")
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
    print("BASELINE SUMMARY (DALL-E 3)")
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
    parser = argparse.ArgumentParser(description="Exp1 Baseline: DALL-E 3 Sprite Generation")
    parser.add_argument("--trials", type=int, default=5, help="Number of trials to run")
    args = parser.parse_args()

    run_experiment(num_trials=args.trials)
