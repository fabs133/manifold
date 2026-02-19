"""
Experiment 3 Control: Structured Data Extraction (Baseline)

Manual retry approach without validation specs.
"""

import os
import sys
import json
import time
import urllib.request
from pathlib import Path
from typing import Dict, Any
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))


SYSTEM_PROMPT = """
Extract customer support data from the email.
Return valid JSON matching this schema:
{
  "customer_id": "string",
  "email": "email address",
  "order_id": "string or null",
  "issue_type": "refund_error|billing|technical|other",
  "priority": 1-5,
  "requires_escalation": boolean,
  "customer_role": "string or null"
}
"""


def extract_baseline(
    email_data: Dict[str, Any],
    api_key: str,
    max_retries: int = 3
) -> Dict[str, Any]:
    """Extract data using baseline approach."""
    trial_id = email_data["_trial_id"]  # sequential ID assigned by run_experiment
    email_text = email_data["email_text"]
    expected = email_data["expected"]
    complexity = email_data["complexity"]

    start_time = time.time()
    attempts = 0
    total_cost = 0.0
    success = False
    duplicate_retry = False
    last_result = None

    for attempt in range(max_retries):
        attempts += 1

        try:
            result = call_gpt4(
                system_prompt=SYSTEM_PROMPT,
                user_message=email_text,
                api_key=api_key
            )

            cost = result["cost"]
            total_cost += cost

            extracted = result["output"]

            # Basic validation (just JSON parsing)
            if isinstance(extracted, dict):
                # Check if has some required fields
                if "customer_id" in extracted and "email" in extracted:
                    success = True
                    last_result = extracted
                    break

            # Check for duplicate retry
            if last_result == extracted:
                duplicate_retry = True

            last_result = extracted

        except Exception as e:
            print(f"Attempt {attempt + 1} error: {e}")
            time.sleep(1)

    elapsed = time.time() - start_time

    # Validate correctness (manual comparison)
    schema_valid = success
    all_required_fields = False
    correct_fields = 0
    hallucinated_fields = []

    if success and last_result:
        # Check required fields
        required = ["customer_id", "email", "issue_type", "priority"]
        all_required_fields = all(f in last_result for f in required)

        # Count correct fields and classify errors
        for key, expected_val in expected.items():
            extracted_val = last_result.get(key)
            if extracted_val == expected_val:
                correct_fields += 1
            elif expected_val is None and extracted_val is not None:
                # Model invented a value for a field that should be null → hallucination
                hallucinated_fields.append(key)

    return {
        "trial_id": trial_id,
        "method": "control",
        "complexity": complexity,

        # Success metrics
        "schema_valid": schema_valid,
        "all_required_fields": all_required_fields,
        "success": schema_valid and all_required_fields,

        # Efficiency
        "attempts_needed": attempts,
        "total_cost": total_cost,
        "time_seconds": elapsed,

        # Retry analysis
        "duplicate_retry": duplicate_retry,

        # Field accuracy
        "correct_fields": correct_fields,
        "total_fields": len(expected),
        "hallucinated_fields": hallucinated_fields,

        # Details
        "extracted": last_result,
        "expected": expected,
        "timestamp": datetime.utcnow().isoformat()
    }


def call_gpt4(system_prompt: str, user_message: str, api_key: str) -> Dict[str, Any]:
    """Call GPT-4 API."""
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "gpt-4o",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ],
        "temperature": 0.3,
        "response_format": {"type": "json_object"}
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

    # Parse JSON
    try:
        output = json.loads(message)
    except json.JSONDecodeError:
        output = {"error": "Failed to parse JSON"}

    # Calculate cost (GPT-4o pricing)
    prompt_tokens = usage.get("prompt_tokens", 0)
    completion_tokens = usage.get("completion_tokens", 0)
    cost = (prompt_tokens / 1_000_000) * 2.50 + (completion_tokens / 1_000_000) * 10.00

    return {
        "output": output,
        "cost": cost,
        "usage": usage
    }


def run_experiment(num_trials: int = 5):
    """Run baseline experiment."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY required")

    # Load dataset
    dataset_path = Path(__file__).parent.parent.parent / "datasets" / "support_emails.json"
    with open(dataset_path) as f:
        emails = json.load(f)

    # Run trials
    results = []
    for i in range(num_trials):
        email_data = emails[i % len(emails)].copy()
        email_data["_trial_id"] = i + 1  # sequential across all repetitions
        print(f"\n=== Trial {i+1}/{num_trials}: {email_data['complexity']} (task {email_data['id']}) ===")

        result = extract_baseline(email_data, api_key)
        results.append(result)

        print(f"Success: {result['success']}")
        print(f"Correct fields: {result['correct_fields']}/{result['total_fields']}")
        print(f"Cost: ${result['total_cost']:.6f}")

        # Small sleep to avoid TPM burst on 50 rapid calls
        if i < num_trials - 1:
            time.sleep(1)

    # Save results (absolute path based on __file__ so it works from any working directory)
    output_path = Path(__file__).resolve().parent.parent / "results" / f"baseline_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w') as f:
        json.dump({
            "experiment": "exp3_extraction_control",
            "trials": num_trials,
            "results": results,
            "summary": calculate_summary(results)
        }, f, indent=2)

    print(f"\n✅ Results saved to: {output_path}")
    print_summary(results)


def calculate_summary(results: list) -> Dict[str, Any]:
    """Calculate summary stats."""
    total = len(results)
    successful = sum(1 for r in results if r["success"])
    avg_attempts = sum(r["attempts_needed"] for r in results) / total
    avg_cost = sum(r["total_cost"] for r in results) / total
    duplicate_retries = sum(1 for r in results if r["duplicate_retry"])
    avg_correct = sum(r["correct_fields"] / r["total_fields"] for r in results) / total

    return {
        "total_trials": total,
        "successful": successful,
        "success_rate": successful / total,
        "avg_attempts": avg_attempts,
        "avg_cost": avg_cost,
        "duplicate_retries": duplicate_retries,
        "duplicate_retry_rate": duplicate_retries / total,
        "avg_field_accuracy": avg_correct
    }


def print_summary(results: list):
    """Print summary."""
    summary = calculate_summary(results)

    print("\n" + "="*60)
    print("BASELINE SUMMARY (Data Extraction)")
    print("="*60)
    print(f"Total Trials:        {summary['total_trials']}")
    print(f"Successful:          {summary['successful']} ({summary['success_rate']:.1%})")
    print(f"Avg Attempts:        {summary['avg_attempts']:.2f}")
    print(f"Avg Cost:            ${summary['avg_cost']:.6f}")
    print(f"Duplicate Retries:   {summary['duplicate_retries']} ({summary['duplicate_retry_rate']:.1%})")
    print(f"Avg Field Accuracy:  {summary['avg_field_accuracy']:.1%}")
    print("="*60)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Exp3 Baseline: Data Extraction")
    parser.add_argument("--trials", type=int, default=5, help="Number of trials")
    args = parser.parse_args()

    run_experiment(num_trials=args.trials)
