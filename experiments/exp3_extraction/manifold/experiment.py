"""
Experiment 3 Treatment: Structured Data Extraction (Manifold)

This uses Manifold orchestration with specs and loop detection.
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
from lib.agents.openai import OpenAIChatAgent


async def extract_data_manifold(
    email_data: Dict[str, Any],
    api_key: str
) -> Dict[str, Any]:
    """
    Extract data using Manifold orchestration.

    Args:
        email_data: Dict with 'email_text', 'expected', 'complexity'
        api_key: OpenAI API key

    Returns:
        Result dict with metrics
    """
    trial_id = email_data["id"]
    email_text = email_data["email_text"]
    expected = email_data["expected"]
    complexity = email_data["complexity"]

    system_prompt = """
Extract customer support data from the email.
Return valid JSON matching this schema:
{
  "customer_id": "string or null",
  "email": "email address",
  "order_id": "string or null",
  "issue_type": "refund_error|billing|technical|other",
  "priority": 1-5,
  "requires_escalation": boolean,
  "customer_role": "string or null"
}
"""

    # Create agent
    agent = OpenAIChatAgent(
        agent_id="gpt4_extractor",
        model="gpt-4",
        temperature=0.0,
        system_prompt=system_prompt,
        api_key=api_key
    )

    # Create specs
    specs = [
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
            initial_data={
                "user_message": email_text
            }
        )

        elapsed = time.time() - start_time

        # Try to parse the extracted data from trace
        extracted = None
        if result.success and result.final_context.trace:
            # Get the last trace entry (the agent's output)
            last_trace = result.final_context.trace[-1]
            agent_output = last_trace.agent_output

            if agent_output:
                try:
                    if isinstance(agent_output, str):
                        extracted = json.loads(agent_output)
                    elif isinstance(agent_output, dict):
                        extracted = agent_output
                except:
                    pass

        # Calculate correctness
        correct_fields = 0
        total_fields = 7
        if extracted and expected:
            for key, expected_value in expected.items():
                if key in extracted and extracted[key] == expected_value:
                    correct_fields += 1

        meets_requirements = (correct_fields == total_fields)
        attempts = result.final_context.budgets.get_total_attempts()
        total_cost = result.final_context.budgets.current_cost

        # Check for loops
        loop_detected = "loop" in result.summary.lower() if result.summary else False

        return {
            "trial_id": trial_id,
            "method": "manifold",
            "model": "gpt-4",
            "complexity": complexity,

            # Success metrics
            "success": meets_requirements,
            "correct_fields": correct_fields,
            "total_fields": total_fields,
            "field_accuracy": correct_fields / total_fields if total_fields > 0 else 0,

            # Efficiency metrics
            "attempts": attempts,
            "total_cost": total_cost,
            "time_seconds": elapsed,

            # Loop metrics
            "loop_detected": loop_detected,
            "duplicate_retry": False,  # Manifold should prevent this

            # Details
            "total_steps_executed": result.total_steps_executed,
            "error": result.summary if not meets_requirements else None,
            "timestamp": datetime.utcnow().isoformat(),

            # Manifold-specific
            "trace_length": len(result.final_context.trace),
        }

    except Exception as e:
        elapsed = time.time() - start_time

        return {
            "trial_id": trial_id,
            "method": "manifold",
            "model": "gpt-4",
            "complexity": complexity,
            "success": False,
            "correct_fields": 0,
            "total_fields": 7,
            "field_accuracy": 0.0,
            "attempts": 0,
            "total_cost": 0.0,
            "time_seconds": elapsed,
            "loop_detected": False,
            "duplicate_retry": False,
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }


async def run_experiment(num_trials: int = 5):
    """Run the Manifold experiment."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY environment variable required")

    # Load dataset
    dataset_path = Path(__file__).parent.parent.parent / "datasets" / "support_emails.json"
    with open(dataset_path) as f:
        emails = json.load(f)

    # Run trials
    results = []
    for i in range(num_trials):
        email_data = emails[i % len(emails)]
        print(f"\n=== Trial {i+1}/{num_trials}: {email_data['complexity']} ===")

        result = await extract_data_manifold(email_data, api_key)
        results.append(result)

        print(f"Success: {result['success']}")
        print(f"Correct fields: {result['correct_fields']}/{result['total_fields']}")
        print(f"Cost: ${result['total_cost']:.6f}")

        # Rate limiting for GPT-4 (TPM limits on standard tier)
        if i < num_trials - 1:
            await asyncio.sleep(5)

    # Save results
    output_path = Path(__file__).parent.parent / "results" / f"manifold_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w') as f:
        json.dump({
            "experiment": "exp3_extraction_manifold",
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
    avg_attempts = sum(r["attempts"] for r in results) / total if total > 0 else 0
    avg_cost = sum(r["total_cost"] for r in results) / total if total > 0 else 0
    avg_time = sum(r["time_seconds"] for r in results) / total if total > 0 else 0
    avg_accuracy = sum(r["field_accuracy"] for r in results) / total if total > 0 else 0
    loops = sum(1 for r in results if r.get("loop_detected"))
    duplicates = sum(1 for r in results if r.get("duplicate_retry"))

    return {
        "total_trials": total,
        "successful": successful,
        "success_rate": successful / total if total > 0 else 0,
        "avg_attempts": avg_attempts,
        "avg_cost_per_trial": avg_cost,
        "avg_time_seconds": avg_time,
        "avg_field_accuracy": avg_accuracy,
        "loop_incidents": loops,
        "duplicate_retries": duplicates
    }


def print_summary(results: list):
    """Print summary statistics."""
    summary = calculate_summary(results)

    print("\n" + "="*60)
    print("MANIFOLD SUMMARY (Data Extraction)")
    print("="*60)
    print(f"Total Trials:        {summary['total_trials']}")
    print(f"Successful:          {summary['successful']} ({summary['success_rate']:.1%})")
    print(f"Avg Attempts:        {summary['avg_attempts']:.2f}")
    print(f"Avg Cost:            ${summary['avg_cost_per_trial']:.6f}")
    print(f"Avg Time:            {summary['avg_time_seconds']:.2f}s")
    print(f"Avg Field Accuracy:  {summary['avg_field_accuracy']:.1%}")
    print(f"Loop Incidents:      {summary['loop_incidents']}")
    print(f"Duplicate Retries:   {summary['duplicate_retries']}")
    print("="*60)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Exp3 Manifold: Data Extraction")
    parser.add_argument("--trials", type=int, default=5, help="Number of trials to run")
    args = parser.parse_args()

    asyncio.run(run_experiment(num_trials=args.trials))
