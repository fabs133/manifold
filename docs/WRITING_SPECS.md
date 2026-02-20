# Writing Specs Guide

Learn how to write custom specification functions for Manifold workflows.

## Table of Contents

- [What is a Spec?](#what-is-a-spec)
- [Spec Anatomy](#spec-anatomy)
- [The Four Categories](#the-four-categories)
- [Writing Effective Specs](#writing-effective-specs)
- [Common Patterns](#common-patterns)
- [Testing Specs](#testing-specs)
- [Best Practices](#best-practices)

---

## What is a Spec?

A **Spec** is a pure validation function that:
- Takes `Context` and optional `candidate` output
- Returns `SpecResult` (passed/failed + metadata)
- Has **NO side effects** (no IO, no mutations)
- Is **deterministic** (same inputs → same output)

Specs are the "laws of physics" in your workflow.

---

## Spec Anatomy

### Basic Structure

```python
from manifold import Spec, SpecResult, Context

class MySpec(Spec):
    """What this spec validates."""

    @property
    def rule_id(self) -> str:
        """Unique, stable identifier."""
        return "my_spec_id"

    @property
    def tags(self) -> tuple[str, ...]:
        """Category labels (optional)."""
        return ("precondition", "data")

    def evaluate(self, context: Context, candidate=None) -> SpecResult:
        """Validation logic."""
        # Check condition
        if condition_met:
            return SpecResult.ok(
                rule_id=self.rule_id,
                message="Success message",
                tags=self.tags
            )

        return SpecResult.fail(
            rule_id=self.rule_id,
            message="Failure message",
            suggested_fix="How to fix this",
            tags=self.tags,
            data={"extra": "info"}
        )
```

### SpecResult Fields

```python
@dataclass(frozen=True)
class SpecResult:
    rule_id: str                  # Required: Same as spec.rule_id
    passed: bool                  # Required: True = passed, False = failed
    message: str                  # Required: Human-readable description
    suggested_fix: str | None     # Optional: How to fix failure
    tags: tuple[str, ...]         # Optional: Category labels
    data: dict[str, Any]          # Optional: Structured failure details
```

---

## The Four Categories

### 1. Pre-Specs (Preconditions)

**When:** BEFORE step executes
**Purpose:** Verify required inputs exist
**Failure:** Step not executed

```python
class HasInputFile(Spec):
    """Pre-condition: input_file must exist in context."""

    @property
    def rule_id(self) -> str:
        return "has_input_file"

    @property
    def tags(self) -> tuple[str, ...]:
        return ("precondition", "data")

    def evaluate(self, context: Context, candidate=None) -> SpecResult:
        if context.has_data("input_file"):
            path = context.get_data("input_file")
            return SpecResult.ok(
                self.rule_id,
                f"Input file: {path}",
                tags=self.tags
            )

        return SpecResult.fail(
            self.rule_id,
            "Missing input_file in context.data",
            suggested_fix="Set context.data['input_file'] = 'path/to/file.txt'",
            tags=self.tags,
            data={"missing_key": "input_file"}
        )
```

**Use when:**
- Checking required context fields
- Validating API keys/credentials
- Verifying files exist
- Ensuring configuration is set

---

### 2. Post-Specs (Postconditions)

**When:** AFTER agent executes
**Purpose:** Validate output before accepting
**Failure:** Output rejected, may retry

```python
class ValidJSON(Spec):
    """Post-condition: output must be valid JSON."""

    @property
    def rule_id(self) -> str:
        return "valid_json"

    @property
    def tags(self) -> tuple[str, ...]:
        return ("postcondition", "format")

    def evaluate(self, context: Context, candidate=None) -> SpecResult:
        if candidate is None:
            return SpecResult.fail(
                self.rule_id,
                "No output to validate",
                suggested_fix="Ensure agent returns output",
                tags=self.tags
            )

        try:
            import json
            parsed = json.loads(candidate)
            return SpecResult.ok(
                self.rule_id,
                f"Valid JSON with {len(parsed)} keys",
                tags=self.tags,
                data={"parsed": parsed}
            )
        except json.JSONDecodeError as e:
            return SpecResult.fail(
                self.rule_id,
                f"Invalid JSON: {e}",
                suggested_fix="Return valid JSON string",
                tags=self.tags,
                data={"error": str(e)}
            )
```

**Use when:**
- Validating output format
- Checking required fields in output
- Verifying data ranges/constraints
- Ensuring schema compliance

---

### 3. Invariant-Specs (Always True)

**When:** At every step
**Purpose:** Enforce global constraints
**Failure:** Workflow stops immediately

```python
class BudgetNotExceeded(Spec):
    """Invariant: budget must never be exceeded."""

    @property
    def rule_id(self) -> str:
        return "budget_not_exceeded"

    @property
    def tags(self) -> tuple[str, ...]:
        return ("invariant", "budget")

    def evaluate(self, context: Context, candidate=None) -> SpecResult:
        budgets = context.budgets

        # Check total attempts
        if budgets.is_total_budget_exceeded():
            return SpecResult.fail(
                self.rule_id,
                f"Total attempts ({budgets.get_total_attempts()}) >= limit ({budgets.max_total_attempts})",
                suggested_fix="Review workflow for loops or increase budget",
                tags=self.tags,
                data={
                    "current": budgets.get_total_attempts(),
                    "max": budgets.max_total_attempts
                }
            )

        # Check cost
        if budgets.is_cost_exceeded():
            return SpecResult.fail(
                self.rule_id,
                f"Cost (${budgets.current_cost:.2f}) >= limit (${budgets.max_cost_dollars:.2f})",
                suggested_fix="Stop workflow, cost limit reached",
                tags=self.tags,
                data={
                    "current_cost": budgets.current_cost,
                    "max_cost": budgets.max_cost_dollars
                }
            )

        return SpecResult.ok(
            self.rule_id,
            f"Budget OK: {budgets.get_total_attempts()} attempts, ${budgets.current_cost:.2f}",
            tags=self.tags
        )
```

**Use when:**
- Budget enforcement
- Security policies
- Data integrity checks
- System-wide constraints

---

### 4. Progress-Specs (Anti-Loop)

**When:** On retry attempts
**Purpose:** Verify situation changed
**Failure:** Prevents identical retry

```python
class SituationChanged(Spec):
    """Progress: context must change between attempts."""

    def __init__(self, step_id: str):
        self._step_id = step_id

    @property
    def rule_id(self) -> str:
        return f"situation_changed:{self._step_id}"

    @property
    def tags(self) -> tuple[str, ...]:
        return ("progress", "anti-loop")

    def evaluate(self, context: Context, candidate=None) -> SpecResult:
        # Get all previous attempts for this step
        traces = context.get_traces_for_step(self._step_id)

        if not traces:
            # First attempt, always ok
            return SpecResult.ok(
                self.rule_id,
                "First attempt",
                tags=self.tags
            )

        last_trace = traces[-1]

        # Check if fewer rules are failing than last time
        last_failures = set(last_trace.failed_rules)
        if last_failures:
            return SpecResult.ok(
                self.rule_id,
                f"Previous attempt had failures: {last_failures}",
                tags=self.tags,
                data={"last_failures": list(last_failures)}
            )

        # Check if new data has been added to context since last attempt
        # (e.g., another step filled in missing fields)
        current_data_keys = set(context.data.keys())
        if len(current_data_keys) > len(traces):
            return SpecResult.ok(
                self.rule_id,
                "Context has new data",
                tags=self.tags,
                data={"data_keys": list(current_data_keys)}
            )

        return SpecResult.fail(
            self.rule_id,
            "No change since last attempt",
            suggested_fix="Retrieve new data or modify approach before retrying",
            tags=self.tags,
            data={"current_keys": list(current_data_keys)}
        )
```

**Use when:**
- Preventing identical retries
- Ensuring new data was retrieved
- Verifying missing fields were filled
- Detecting stuck workflows

---

## Writing Effective Specs

### Rule 1: Keep It Pure

**✅ Good:**
```python
def evaluate(self, context: Context, candidate=None):
    value = context.get_data("field")
    return SpecResult.ok(...) if value > 0 else SpecResult.fail(...)
```

**❌ Bad:**
```python
def evaluate(self, context: Context, candidate=None):
    # Don't do IO!
    with open("file.txt") as f:
        data = f.read()

    # Don't mutate!
    context.data["checked"] = True

    return SpecResult.ok(...)
```

### Rule 2: Always Provide suggested_fix

**✅ Good:**
```python
return SpecResult.fail(
    self.rule_id,
    "Missing API key",
    suggested_fix="Set context.data['api_key'] = 'sk-...'",
    tags=self.tags
)
```

**❌ Bad:**
```python
return SpecResult.fail(
    self.rule_id,
    "Missing API key",  # How do I fix this?
    tags=self.tags
)
```

### Rule 3: Use Structured Data

**✅ Good:**
```python
return SpecResult.fail(
    self.rule_id,
    "Missing 3 required fields",
    suggested_fix="Add fields: customer_id, amount, date",
    data={
        "missing_fields": ["customer_id", "amount", "date"],
        "present_fields": ["name", "email"]
    }
)
```

**❌ Bad:**
```python
return SpecResult.fail(
    self.rule_id,
    "Missing fields",  # Which ones?
)
```

### Rule 4: Make rule_id Stable

**✅ Good:**
```python
@property
def rule_id(self) -> str:
    return "has_required_fields"  # Never changes
```

**❌ Bad:**
```python
@property
def rule_id(self) -> str:
    return f"check_{time.time()}"  # Changes every time!
```

---

## Common Patterns

### Pattern 1: Field Existence Check

```python
class HasField(Spec):
    def __init__(self, field_name: str):
        self._field = field_name

    @property
    def rule_id(self) -> str:
        return f"has_field:{self._field}"

    def evaluate(self, context: Context, candidate=None):
        if context.has_data(self._field):
            return SpecResult.ok(self.rule_id, f"Field '{self._field}' present")
        return SpecResult.fail(
            self.rule_id,
            f"Missing field: {self._field}",
            suggested_fix=f"Set context.data['{self._field}']"
        )
```

### Pattern 2: Schema Validation

```python
class MatchesSchema(Spec):
    def __init__(self, required_fields: list[str]):
        self._required = required_fields

    @property
    def rule_id(self) -> str:
        return "matches_schema"

    def evaluate(self, context: Context, candidate=None):
        if not candidate or not isinstance(candidate, dict):
            return SpecResult.fail(
                self.rule_id,
                "Output must be a dictionary"
            )

        missing = [f for f in self._required if f not in candidate]
        if missing:
            return SpecResult.fail(
                self.rule_id,
                f"Missing {len(missing)} required fields",
                suggested_fix=f"Add fields: {', '.join(missing)}",
                data={"missing_fields": missing}
            )

        return SpecResult.ok(
            self.rule_id,
            "All required fields present"
        )
```

### Pattern 3: Range Validation

```python
class InRange(Spec):
    def __init__(self, field: str, min_val: float, max_val: float):
        self._field = field
        self._min = min_val
        self._max = max_val

    @property
    def rule_id(self) -> str:
        return f"in_range:{self._field}"

    def evaluate(self, context: Context, candidate=None):
        value = context.get_data(self._field)
        if value is None:
            return SpecResult.fail(
                self.rule_id,
                f"Field '{self._field}' not found"
            )

        if self._min <= value <= self._max:
            return SpecResult.ok(
                self.rule_id,
                f"{self._field}={value} in range [{self._min}, {self._max}]"
            )

        return SpecResult.fail(
            self.rule_id,
            f"{self._field}={value} out of range [{self._min}, {self._max}]",
            suggested_fix=f"Set {self._field} between {self._min} and {self._max}",
            data={"value": value, "min": self._min, "max": self._max}
        )
```

---

## Testing Specs

Always test your specs!

```python
import pytest
from manifold import Context, create_context

def test_has_field_spec_pass():
    spec = HasField("api_key")
    ctx = create_context(
        run_id="test",
        initial_data={"api_key": "sk-123"}
    )

    result = spec.evaluate(ctx)

    assert result.passed
    assert result.rule_id == "has_field:api_key"
    assert "present" in result.message


def test_has_field_spec_fail():
    spec = HasField("api_key")
    ctx = create_context(run_id="test", initial_data={})

    result = spec.evaluate(ctx)

    assert not result.passed
    assert result.suggested_fix is not None
    assert "api_key" in result.suggested_fix
```

---

## Best Practices

### DO:
✅ Keep specs fast (< 1ms)
✅ Make them pure (no side effects)
✅ Provide clear error messages
✅ Include suggested_fix for all failures
✅ Use structured data for complex failures
✅ Write unit tests for each spec
✅ Make rule_id stable and descriptive

### DON'T:
❌ Perform IO operations
❌ Mutate context
❌ Make specs non-deterministic
❌ Return vague error messages
❌ Forget suggested_fix
❌ Make rule_id dynamic
❌ Skip testing

---

## Next Steps

- [Manifest Schema](MANIFEST_SCHEMA.md) - Reference specs in manifests
- [Core Concepts](CONCEPTS.md) - Understanding the architecture
- [Examples](../examples/) - See specs in action
