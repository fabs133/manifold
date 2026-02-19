"""
Experiment 2 Treatment: gpt-image-1 Sprite Generation (Manifold)

Uses Manifold orchestration with specs and loop detection.
Mirrors EXP1 exactly, but uses gpt-image-1 instead of dall-e-3.

Key differences vs EXP1:
- model="gpt-image-1" (not "dall-e-3")
- gpt-image-1 does NOT need quality param (ignored / causes error)
- gpt-image-1 rate limit: ~7 img/min at Tier 3 → 10s sleep
- gpt-image-1 returns b64_json (no URL) — image_agent handles this
"""

import os
import sys
import json
import time
import asyncio
from pathlib import Path
from typing import Dict, Any
from datetime import datetime

# Add manifold repo root and experiments dir to path
_repo_root = str(Path(__file__).parent.parent.parent.parent)
_experiments_root = str(Path(__file__).parent.parent.parent)
sys.path.insert(0, _repo_root)
sys.path.insert(0, _experiments_root)

from manifold import (
    OrchestratorBuilder,
    Context,
    create_context,
    BudgetNotExceeded,
)
from lib.agents.openai import OpenAIImageAgent
from examples.sprite_generation.harness.specs import ImageDimensionsSpec


async def generate_sprite_manifold(
    prompt_data: Dict[str, Any],
    api_key: str
) -> Dict[str, Any]:
    """
    Generate sprite using Manifold orchestration with gpt-image-1.

    Args:
        prompt_data: Dict with 'description', 'frames', 'style', 'expected_grid',
                     '_trial_id' (sequential, injected by run_experiment)
        api_key: OpenAI API key

    Returns:
        Result dict with metrics
    """
    trial_id = prompt_data["_trial_id"]
    description = prompt_data["description"]
    frames = prompt_data["frames"]
    style = prompt_data["style"]
    expected_grid = prompt_data["expected_grid"]

    # Build structured prompt (same as EXP1 manifold approach)
    grid_size = int(expected_grid.split('x')[0])
    prompt = f"""
STRICT GRID LAYOUT: Create a {grid_size}x{grid_size} grid of {frames} sprites.

CONTENT: {description}

STYLE: {style}

CONSTRAINTS:
- Each sprite must be clearly separated
- Grid must be exactly {grid_size}x{grid_size}
- Consistent style across all sprites
- Clear background separation
    """.strip()

    # Create agent — gpt-image-1 does not use quality param
    agent = OpenAIImageAgent(
        agent_id="gptimage1_generator",
        model="gpt-image-1",
        size="1024x1024",
        api_key=api_key
    )

    # Create specs
    specs = [
        ImageDimensionsSpec(min_width=1024, min_height=1024),
        BudgetNotExceeded(),
    ]

    # Build orchestrator
    manifest_path = Path(__file__).parent / "workflow.yaml"

    orchestrator = (
        OrchestratorBuilder()
        .with_manifest_file(str(manifest_path))
        .with_agent(agent)
        .with_specs(specs)
        .build()
    )

    # Run workflow
    start_time = time.time()

    try:
        result = await orchestrator.run(
            initial_data={"prompt": prompt}
        )

        elapsed = time.time() - start_time

        # Extract metrics from result
        meets_requirements = result.success
        attempts = result.final_context.budgets.get_total_attempts()
        total_cost = result.final_context.budgets.current_cost

        # Check for loops (semantic loop detection)
        loop_detected = False
        for trace in result.final_context.trace:
            if trace.error and "loop" in trace.error.lower():
                loop_detected = True
                break

        # Count duplicate failures
        duplicate_failures = 0
        failed_steps = [t for t in result.final_context.trace if t.error]
        if len(failed_steps) >= 2:
            step_failures = {}
            for trace in failed_steps:
                step_failures[trace.step_id] = step_failures.get(trace.step_id, 0) + 1
            duplicate_failures = max(step_failures.values()) - 1 if step_failures else 0

        return {
            "trial_id": trial_id,
            "method": "manifold",
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
            "total_steps_executed": result.total_steps_executed,
            "error": result.summary if not meets_requirements else None,
            "timestamp": datetime.utcnow().isoformat(),

            # Manifold-specific
            "trace_length": len(result.final_context.trace),
            "spec_failures": len([
                t for t in result.final_context.trace
                for s in t.spec_results
                if not s.passed
            ])
        }

    except Exception as e:
        elapsed = time.time() - start_time

        return {
            "trial_id": trial_id,
            "method": "manifold",
            "model": "gpt-image-1",
            "description": description,
            "meets_requirements": False,
            "success": False,
            "attempts_needed": 0,
            "total_cost": 0.0,
            "time_seconds": elapsed,
            "loop_detected": False,
            "duplicate_failures": 0,
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }


async def run_experiment(num_trials: int = 5):
    """Run the Manifold experiment."""
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
    print("MANIFOLD EXPERIMENT: gpt-image-1 Sprite Generation")
    print(f"{'='*60}")
    print(f"Trials: {num_trials}")
    print(f"Dataset: {len(prompts)} prompts (cycling)")
    print()

    results = []
    for i in range(num_trials):
        prompt_data = prompts[i % len(prompts)].copy()
        prompt_data["_trial_id"] = i + 1  # sequential IDs 1..num_trials
        print(f"\n=== Trial {i+1}/{num_trials}: {prompt_data['description']} (task {prompt_data['id']}) ===")

        result = await generate_sprite_manifold(prompt_data, api_key)
        results.append(result)

        print(f"Success: {result['success']}")
        print(f"Attempts: {result['attempts_needed']}")
        print(f"Cost: ${result['total_cost']:.4f}")
        print(f"Time: {result['time_seconds']:.2f}s")
        if result.get('loop_detected'):
            print("WARNING: LOOP DETECTED")

        # Progress
        successes = sum(1 for r in results if r["success"])
        print(f"Running: {successes}/{len(results)} ({successes/len(results)*100:.1f}%) successful")

        # Rate limit: gpt-image-1 Tier 3 ~7 img/min
        # 10s delay = 6 img/min, safely under limit
        if i < num_trials - 1:
            await asyncio.sleep(10)

    # Save results
    output_path = Path(__file__).resolve().parent.parent / "results" / f"manifold_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w') as f:
        json.dump({
            "experiment": "exp2_gptimage1_manifold",
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
    avg_attempts = sum(r["attempts_needed"] for r in results) / total if total > 0 else 0
    avg_cost = sum(r["total_cost"] for r in results) / total if total > 0 else 0
    avg_time = sum(r["time_seconds"] for r in results) / total if total > 0 else 0
    loops = sum(1 for r in results if r.get("loop_detected"))

    return {
        "total_trials": total,
        "successful": successful,
        "success_rate": successful / total if total > 0 else 0,
        "avg_attempts": avg_attempts,
        "avg_cost_per_trial": avg_cost,
        "avg_time_seconds": avg_time,
        "loop_incidents": loops,
        "loop_rate": loops / total if total > 0 else 0
    }


def print_summary(results: list):
    """Print summary statistics."""
    summary = calculate_summary(results)

    print("\n" + "="*60)
    print("MANIFOLD SUMMARY (gpt-image-1)")
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
    parser = argparse.ArgumentParser(description="Exp2 Manifold: gpt-image-1 Sprite Generation")
    parser.add_argument("--trials", type=int, default=5, help="Number of trials to run")
    args = parser.parse_args()

    asyncio.run(run_experiment(num_trials=args.trials))
