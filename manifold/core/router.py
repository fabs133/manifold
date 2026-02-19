"""
Router - Edge condition evaluation and next-step selection.

The Router determines which step comes next based on:
- Current step's outgoing edges
- Edge conditions evaluated against context/spec results
- Edge priorities (higher priority edges checked first)

Key principle: The Router only reads; it doesn't execute.
It returns the next step ID (or terminal states).
"""

from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from manifold.core.context import Context, TraceEntry
    from manifold.core.manifest import Edge, Manifest


# Terminal states
COMPLETE = "__complete__"
FAIL = "__fail__"


class ConditionEvaluator:
    """
    Evaluates edge condition expressions.

    Conditions are simple expressions that can reference:
    - post_ok: All post_specs passed
    - invariant_ok: All invariant_specs passed
    - passed("rule_id"): Specific spec passed
    - failed("rule_id"): Specific spec failed
    - has("field"): Context has data field
    - attempts("step_id") < N: Attempt count check
    - true / false: Literal booleans
    - and / or / not: Logical operators

    Examples:
        "post_ok"
        "post_ok and invariant_ok"
        "failed('balance_check') and attempts('balance') < 3"
        "has('game_config') and passed('config_valid')"
    """

    def __init__(self, context: "Context", trace_entry: "TraceEntry | None" = None):
        """
        Initialize evaluator with current state.

        Args:
            context: Current workflow context
            trace_entry: Most recent trace entry (for spec results)
        """
        self._context = context
        self._trace_entry = trace_entry
        self._spec_results: dict[str, bool] = {}

        # Build spec results lookup
        if trace_entry:
            for sr in trace_entry.spec_results:
                self._spec_results[sr.rule_id] = sr.passed

    def evaluate(self, condition: str) -> bool:
        """
        Evaluate a condition expression.

        Args:
            condition: The condition string to evaluate

        Returns:
            True if condition passes, False otherwise
        """
        # Handle literal booleans
        condition = condition.strip()
        if condition.lower() == "true":
            return True
        if condition.lower() == "false":
            return False

        # Build evaluation context
        eval_context = {
            "post_ok": self._post_ok(),
            "invariant_ok": self._invariant_ok(),
            "passed": self._passed,
            "failed": self._failed,
            "has": self._has,
            "attempts": self._attempts,
            "True": True,
            "False": False,
        }

        try:
            # Safe eval with restricted context
            return bool(eval(condition, {"__builtins__": {}}, eval_context))
        except Exception as e:
            # Invalid condition - treat as false and log
            print(f"Warning: Invalid condition '{condition}': {e}")
            return False

    def _post_ok(self) -> bool:
        """Check if all post_specs passed."""
        if not self._trace_entry:
            return True  # No trace = no failures

        # Check if any spec with "postcondition" tag failed
        for sr in self._trace_entry.spec_results:
            if not sr.passed and "postcondition" in sr.tags:
                return False
        return True

    def _invariant_ok(self) -> bool:
        """Check if all invariant_specs passed."""
        if not self._trace_entry:
            return True

        for sr in self._trace_entry.spec_results:
            if not sr.passed and "invariant" in sr.tags:
                return False
        return True

    def _passed(self, rule_id: str) -> bool:
        """Check if specific spec passed."""
        return self._spec_results.get(rule_id, False)

    def _failed(self, rule_id: str) -> bool:
        """Check if specific spec failed."""
        if rule_id not in self._spec_results:
            return False  # Unknown spec = not failed
        return not self._spec_results[rule_id]

    def _has(self, field: str) -> bool:
        """Check if context has data field."""
        return self._context.has_data(field)

    def _attempts(self, step_id: str) -> int:
        """Get attempt count for a step."""
        return self._context.budgets.get_step_attempts(step_id)


class Router:
    """
    Determines next step based on edges and conditions.

    The Router:
    1. Gets edges from current step
    2. Evaluates edge conditions in priority order
    3. Returns first matching edge's target

    Usage:
        router = Router(manifest)
        next_step = router.route(current_step, context, trace_entry)
    """

    def __init__(self, manifest: "Manifest"):
        """
        Initialize router with manifest.

        Args:
            manifest: The workflow manifest containing edge definitions
        """
        self._manifest = manifest

    def route(
        self, current_step: str, context: "Context", trace_entry: "TraceEntry | None" = None
    ) -> str:
        """
        Determine next step from current step.

        Args:
            current_step: Current step ID
            context: Current workflow context
            trace_entry: Most recent trace entry (for spec results)

        Returns:
            Next step ID, or COMPLETE/FAIL terminal states
        """
        # Get edges from current step (already sorted by priority)
        edges = self._manifest.get_edges_from(current_step)

        if not edges:
            # No outgoing edges = workflow complete
            return COMPLETE

        # Create evaluator
        evaluator = ConditionEvaluator(context, trace_entry)

        # Evaluate edges in priority order
        for edge in edges:
            if evaluator.evaluate(edge.when):
                return edge.to_step

        # No edge matched - this is a problem
        # Default to FAIL to prevent stuck workflows
        return FAIL

    def get_eligible_edges(
        self, current_step: str, context: "Context", trace_entry: "TraceEntry | None" = None
    ) -> list["Edge"]:
        """
        Get all edges whose conditions pass.

        Useful for debugging/visualization.

        Args:
            current_step: Current step ID
            context: Current workflow context
            trace_entry: Most recent trace entry

        Returns:
            List of edges with passing conditions
        """
        edges = self._manifest.get_edges_from(current_step)
        evaluator = ConditionEvaluator(context, trace_entry)

        return [edge for edge in edges if evaluator.evaluate(edge.when)]

    def explain_routing(
        self, current_step: str, context: "Context", trace_entry: "TraceEntry | None" = None
    ) -> dict[str, Any]:
        """
        Explain the routing decision for debugging.

        Returns detailed information about which edges were
        considered and why.

        Args:
            current_step: Current step ID
            context: Current workflow context
            trace_entry: Most recent trace entry

        Returns:
            Dict with routing explanation
        """
        edges = self._manifest.get_edges_from(current_step)
        evaluator = ConditionEvaluator(context, trace_entry)

        edge_evaluations = []
        selected = None

        for edge in edges:
            result = evaluator.evaluate(edge.when)
            edge_info = {
                "to_step": edge.to_step,
                "condition": edge.when,
                "priority": edge.priority,
                "passed": result,
            }
            edge_evaluations.append(edge_info)

            if result and selected is None:
                selected = edge.to_step

        return {
            "current_step": current_step,
            "edges_evaluated": len(edges),
            "edge_details": edge_evaluations,
            "selected_next": selected or FAIL,
            "context_data_keys": list(context.data.keys()),
            "attempt_counts": dict(context.budgets.current_attempts),
        }


class RetryRouter:
    """
    Specialized router for retry decisions.

    Handles the common pattern of:
    - Retry same step if specs failed and budget allows
    - Move to next step if all specs passed
    - Fail if budget exceeded
    """

    def __init__(self, max_attempts_per_step: int = 3):
        """
        Initialize retry router.

        Args:
            max_attempts_per_step: Maximum retries before giving up
        """
        self._max_attempts = max_attempts_per_step

    def should_retry(self, step_id: str, context: "Context", trace_entry: "TraceEntry") -> bool:
        """
        Determine if step should be retried.

        Args:
            step_id: The step being considered for retry
            context: Current workflow context
            trace_entry: The trace entry from the failed attempt

        Returns:
            True if retry should be attempted
        """
        # Check if step passed
        if trace_entry.passed:
            return False  # No retry needed

        # Check budget
        attempts = context.budgets.get_step_attempts(step_id)
        if attempts >= self._max_attempts:
            return False  # Budget exceeded

        # Check for recoverable failures
        # (failures with suggested fixes are potentially recoverable)
        has_recoverable = any(
            sr.suggested_fix is not None for sr in trace_entry.spec_results if not sr.passed
        )

        return has_recoverable

    def get_retry_info(
        self, step_id: str, context: "Context", trace_entry: "TraceEntry"
    ) -> dict[str, Any]:
        """
        Get information about retry decision.

        Args:
            step_id: The step being considered
            context: Current workflow context
            trace_entry: The trace entry from the attempt

        Returns:
            Dict with retry decision details
        """
        attempts = context.budgets.get_step_attempts(step_id)
        failures = [sr for sr in trace_entry.spec_results if not sr.passed]

        return {
            "step_id": step_id,
            "current_attempts": attempts,
            "max_attempts": self._max_attempts,
            "budget_remaining": self._max_attempts - attempts,
            "passed": trace_entry.passed,
            "failure_count": len(failures),
            "failures": [
                {
                    "rule_id": sr.rule_id,
                    "message": sr.message,
                    "suggested_fix": sr.suggested_fix,
                    "recoverable": sr.suggested_fix is not None,
                }
                for sr in failures
            ],
            "should_retry": self.should_retry(step_id, context, trace_entry),
        }
