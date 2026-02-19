"""
Experiment 3 Smart Control: Engineered Data Extraction

Represents what a competent engineer would build:
- Structured system message with clear schema
- Multi-stage validation (schema, types, formats)
- Context-aware retry (hints about previous failure)
- Duplicate detection

This is the REAL comparison for Manifold.
"""

import os
import sys
import json
import time
import urllib.request
from pathlib import Path
from typing import Dict, List, Tuple
from datetime import datetime

# Add shared utilities
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from shared.validation_utils import SchemaValidator


class SmartExtractor:
    """
    Smart baseline: well-engineered extraction.

    Key features:
    - System message for consistent behavior
    - Explicit schema definition
    - Multi-stage validation (presence, types, formats)
    - Context hints (tells model what failed last time)
    - Duplicate detection
    """

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.validator = SchemaValidator()

    def _build_system_message(self) -> str:
        """Engineered system message for reliable extraction."""
        return """You are an expert data extraction system for customer support emails.

Your task: Extract structured data following a strict schema.

Quality standards:
1. Return ONLY valid JSON (no markdown, no explanation text)
2. Follow schema exactly (never omit required fields)
3. Use null for missing fields (never leave undefined)
4. Validate formats before returning:
   - Email: must match xxx@yyy.zzz
   - Priority: must be integer 1-5
   - Issue type: must be from allowed enum
   - Customer ID: must match CUST-XXXXX format
   - Order ID: must match ORD-XXXXX format
5. If uncertain about a value, use null and explain in _notes field

Critical: Precision is mandatory. Invalid data causes production failures."""

    def _build_schema_definition(self) -> str:
        """Clear schema definition."""
        return """Required JSON schema:

{
  "customer_id": "string (format: CUST-XXXXX) or null",
  "email": "string (valid email address) or null",
  "order_id": "string (format: ORD-XXXXX) or null",
  "issue_type": "enum: refund_error|billing|technical|other",
  "priority": "integer 1-5 (5=critical, 1=low)",
  "requires_escalation": "boolean",
  "customer_role": "string or null",
  "_notes": "string (optional, for uncertain extractions)"
}"""

    def _build_extraction_prompt(
        self,
        email_text: str,
        context_hints: List[str] = None
    ) -> str:
        """
        Build extraction prompt with optional context hints.

        Context hints tell the model what failed last time,
        so it can correct specific issues.
        """
        prompt = f"Extract customer support data from this email:\n\n{email_text}\n\n"
        prompt += self._build_schema_definition()

        if context_hints:
            prompt += "\n\n Previous attempt had these issues:"
            for hint in context_hints:
                prompt += f"\n- {hint}"
            prompt += "\n\nPlease address these specific validation errors."

        return prompt

    def _validate_comprehensive(
        self,
        data: Dict
    ) -> Tuple[bool, List[str]]:
        """
        Multi-stage validation.

        Stage 1: Required fields present
        Stage 2: Type validation
        Stage 3: Format validation

        Returns: (success, list_of_errors)
        """
        errors = []

        # Stage 1: Required fields
        required = ["customer_id", "email", "order_id", "issue_type", "priority", "requires_escalation"]
        has_required, missing = self.validator.validate_required_fields(data, required)

        if not has_required:
            for field in missing:
                errors.append(f"missing_field:{field}")
            return False, errors

        # Stage 2: Type validation
        if not isinstance(data["priority"], int):
            errors.append(f"invalid_type:priority (got {type(data['priority']).__name__}, need int)")

        if not isinstance(data["requires_escalation"], bool):
            errors.append(f"invalid_type:requires_escalation (got {type(data['requires_escalation']).__name__}, need bool)")

        if errors:
            return False, errors

        # Stage 3: Format validation

        # Priority range
        valid, msg = self.validator.validate_range(data["priority"], 1, 5, "priority")
        if not valid:
            errors.append(f"invalid_range:priority={data['priority']}")

        # Issue type enum
        valid, msg = self.validator.validate_enum(
            data["issue_type"],
            ["refund_error", "billing", "technical", "other"],
            "issue_type"
        )
        if not valid:
            errors.append(f"invalid_enum:issue_type={data['issue_type']}")

        # Email format
        if data["email"]:
            valid, msg = self.validator.validate_email(data["email"])
            if not valid:
                errors.append(f"invalid_format:email={data['email']}")

        # Customer ID format
        if data["customer_id"]:
            valid, msg = self.validator.validate_pattern(
                data["customer_id"],
                r'^CUST-\d+$',
                "customer_id"
            )
            if not valid:
                errors.append(f"invalid_format:customer_id={data['customer_id']}")

        # Order ID format
        if data["order_id"]:
            valid, msg = self.validator.validate_pattern(
                data["order_id"],
                r'^ORD-\d+$',
                "order_id"
            )
            if not valid:
                errors.append(f"invalid_format:order_id={data['order_id']}")

        success = len(errors) == 0
        return success, errors

    def extract(
        self,
        email_text: str,
        max_attempts: int = 3
    ) -> Dict:
        """
        Extract with smart retry.

        Returns detailed metrics for benchmarking.
        """
        start_time = time.time()

        result = {
            "success": False,
            "data": None,
            "attempts": 0,
            "total_cost": 0.0,
            "time_seconds": 0.0,
            "validation_history": [],
            "context_hints_used": [],
            "duplicate_retry": False
        }

        context_hints = []
        seen_responses = set()

        for attempt in range(1, max_attempts + 1):
            result["attempts"] = attempt

            print(f"   Attempt {attempt}/{max_attempts}")
            if context_hints:
                print(f"   Context hints: {context_hints[:2]}")  # Show first 2

            try:
                # Build prompt with context
                prompt = self._build_extraction_prompt(email_text, context_hints)

                # Call GPT-4o
                response_content = self._call_gpt4o(prompt)
                result["total_cost"] += 0.01  # Approximate GPT-4o cost

                # Duplicate detection
                response_hash = hash(response_content)
                if response_hash in seen_responses:
                    result["duplicate_retry"] = True
                    print(f"     Duplicate response (blind retry)")
                seen_responses.add(response_hash)

                # Parse JSON
                try:
                    data = json.loads(response_content)
                except json.JSONDecodeError as e:
                    print(f"   [FAIL] Invalid JSON: {e}")
                    result["validation_history"].append({
                        "attempt": attempt,
                        "error": "invalid_json",
                        "details": str(e)
                    })
                    context_hints = ["Return valid JSON only, no markdown or extra text"]
                    result["context_hints_used"].append(context_hints)
                    continue

                # Validate
                success, errors = self._validate_comprehensive(data)

                result["validation_history"].append({
                    "attempt": attempt,
                    "success": success,
                    "errors": errors
                })

                print(f"   Validation: {'[PASS] PASS' if success else f'[FAIL] FAIL ({len(errors)} errors)'}")
                if errors:
                    print(f"   Errors: {errors[:3]}")  # Show first 3

                if success:
                    result["success"] = True
                    result["data"] = data
                    break
                else:
                    # Build context hints for next attempt
                    context_hints = errors[:5]  # Top 5 errors
                    result["context_hints_used"].append(context_hints)

            except Exception as e:
                print(f"   [FAIL] Error: {e}")
                result["validation_history"].append({
                    "attempt": attempt,
                    "error": str(e)
                })
                break

        result["time_seconds"] = time.time() - start_time
        return result

    def _call_gpt4o(self, prompt: str) -> str:
        """Call GPT-4o API."""
        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": "gpt-4o",
            "messages": [
                {"role": "system", "content": self._build_system_message()},
                {"role": "user", "content": prompt}
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

        return result["choices"][0]["message"]["content"]


def run_experiment(num_trials: int = 5):
    """Run smart control extraction experiment."""
    # Load .env from experiments root
    env_path = Path(__file__).parent.parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("[ERROR] OPENAI_API_KEY not set")
        print("Run: python ../../setup_api_key.py")
        sys.exit(1)

    # Load dataset
    dataset_path = Path(__file__).parent.parent.parent / "datasets" / "support_emails.json"
    with open(dataset_path) as f:
        emails = json.load(f)

    print(f"\n{'='*60}")
    print("SMART CONTROL EXPERIMENT: Data Extraction")
    print(f"{'='*60}")
    print(f"Trials: {num_trials}")
    print()

    extractor = SmartExtractor(api_key)
    results = []

    for i in range(num_trials):
        email_data = emails[i % len(emails)]

        print(f"\n{'====='*60}")
        print(f"TRIAL {i+1}/{num_trials}")
        print(f"Email ID: {email_data['id']}")
        print(f"Complexity: {email_data['complexity']}")
        print(f"{'====='*60}")

        result = extractor.extract(
            email_text=email_data['email_text'],
            max_attempts=3
        )

        # Add metadata
        result["trial_id"] = i + 1
        result["method"] = "smart_control"
        result["email_id"] = email_data["id"]
        result["complexity"] = email_data["complexity"]
        result["timestamp"] = datetime.utcnow().isoformat()

        # Check accuracy against expected
        if result["success"] and "expected" in email_data:
            correct_fields = sum(
                1 for k, v in email_data["expected"].items()
                if result["data"].get(k) == v
            )
            result["correct_fields"] = correct_fields
            result["total_expected_fields"] = len(email_data["expected"])
            result["field_accuracy"] = correct_fields / len(email_data["expected"])

        results.append(result)

        # Rate limiting for GPT-4
        if i < num_trials - 1:
            time.sleep(5)

        # Progress
        successes = sum(1 for r in results if r["success"])
        success_rate = successes / len(results) * 100
        avg_cost = sum(r["total_cost"] for r in results) / len(results)
        duplicates = sum(1 for r in results if r.get("duplicate_retry"))

        print(f"\n[PROGRESS] Progress:")
        print(f"   Success: {successes}/{len(results)} ({success_rate:.1f}%)")
        print(f"   Avg cost: ${avg_cost:.6f}")
        print(f"   Duplicate retries: {duplicates}")

    # Save results
    output_path = Path(__file__).parent.parent / "results" / f"smart_control_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w') as f:
        json.dump({
            "experiment": "exp3_extraction_smart_control",
            "trials": num_trials,
            "results": results,
            "summary": {
                "total_trials": num_trials,
                "successful": sum(1 for r in results if r["success"]),
                "success_rate": sum(1 for r in results if r["success"]) / num_trials,
                "avg_attempts": sum(r["attempts"] for r in results) / num_trials,
                "avg_cost": sum(r["total_cost"] for r in results) / num_trials,
                "duplicate_retries": sum(1 for r in results if r.get("duplicate_retry")),
                "avg_field_accuracy": sum(r.get("field_accuracy", 0) for r in results if r["success"]) / max(sum(1 for r in results if r["success"]), 1)
            }
        }, f, indent=2)

    print(f"\n[PASS] Results saved to: {output_path}")

    # Print summary
    summary = json.load(open(output_path))["summary"]
    print(f"\n{'='*60}")
    print("SMART CONTROL SUMMARY (Data Extraction)")
    print(f"{'='*60}")
    print(f"Total Trials:        {summary['total_trials']}")
    print(f"Successful:          {summary['successful']} ({summary['success_rate']:.1%})")
    print(f"Avg Attempts:        {summary['avg_attempts']:.2f}")
    print(f"Avg Cost:            ${summary['avg_cost']:.6f}")
    print(f"Duplicate Retries:   {summary['duplicate_retries']}")
    print(f"Avg Field Accuracy:  {summary['avg_field_accuracy']:.1%}")
    print(f"{'='*60}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Exp3 Smart Control: Engineered Extraction")
    parser.add_argument("--trials", type=int, default=5, help="Number of trials")
    args = parser.parse_args()

    run_experiment(num_trials=args.trials)
