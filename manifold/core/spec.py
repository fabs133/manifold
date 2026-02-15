"""
Spec - Pure validation functions for contract enforcement.

Specs are the "laws of physics" in the workflow system:
- Pure: No IO, no state mutation
- Deterministic: Same inputs → same outputs
- Composable: Can be combined into spec lists

Spec Categories:
- pre_specs: Must pass before step runs
- post_specs: Must pass for output to be accepted
- invariant_specs: Must always hold (global constraints)
- progress_specs: Must show situation changed (anti-loop)
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from manifold.core.context import Context


@dataclass(frozen=True)
class SpecResult:
    """
    Result of evaluating a spec.

    This is the universal output format for all specs.
    It provides enough information for:
    - Pass/fail determination
    - Error messages for humans
    - Suggested fixes for self-correction
    - Structured data for programmatic handling
    """
    rule_id: str
    passed: bool
    message: str
    suggested_fix: str | None = None
    tags: tuple[str, ...] = ()
    data: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def ok(
        cls,
        rule_id: str,
        message: str = "Passed",
        tags: tuple[str, ...] = (),
        data: dict[str, Any] | None = None
    ) -> "SpecResult":
        """Create a passing result."""
        return cls(
            rule_id=rule_id,
            passed=True,
            message=message,
            tags=tags,
            data=data or {}
        )

    @classmethod
    def fail(
        cls,
        rule_id: str,
        message: str,
        suggested_fix: str | None = None,
        tags: tuple[str, ...] = (),
        data: dict[str, Any] | None = None
    ) -> "SpecResult":
        """Create a failing result."""
        return cls(
            rule_id=rule_id,
            passed=False,
            message=message,
            suggested_fix=suggested_fix,
            tags=tags,
            data=data or {}
        )

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "rule_id": self.rule_id,
            "passed": self.passed,
            "message": self.message,
            "suggested_fix": self.suggested_fix,
            "tags": list(self.tags),
            "data": self.data
        }

    def to_trace_ref(self) -> "SpecResultRef":
        """Convert to lightweight trace reference."""
        from manifold.core.context import SpecResultRef
        return SpecResultRef(
            rule_id=self.rule_id,
            passed=self.passed,
            message=self.message,
            suggested_fix=self.suggested_fix,
            tags=self.tags,
            data=self.data
        )


class Spec(ABC):
    """
    Base class for all specs.

    A Spec is a pure validation function:
    - No IO operations
    - No state mutation
    - Deterministic given inputs
    - Returns structured SpecResult

    Subclasses must implement:
    - rule_id: Stable string identifier
    - evaluate(): The validation logic
    """

    @property
    @abstractmethod
    def rule_id(self) -> str:
        """Unique, stable identifier for this spec."""
        pass

    @property
    def tags(self) -> tuple[str, ...]:
        """Category labels for this spec."""
        return ()

    @abstractmethod
    def evaluate(self, context: "Context", candidate: Any = None) -> SpecResult:
        """
        Evaluate the spec.

        Args:
            context: Current workflow context
            candidate: Optional output to validate (for post_specs)

        Returns:
            SpecResult with pass/fail and details

        Contract:
            - Must be pure (no side effects)
            - Must be deterministic
            - Must return SpecResult
        """
        pass

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(rule_id={self.rule_id!r})"


class SpecEngine:
    """
    Engine for evaluating lists of specs.

    The SpecEngine is the central point for running specs.
    It handles:
    - Batch evaluation of spec lists
    - Result aggregation
    - Spec registry management
    """

    def __init__(self):
        self._registry: dict[str, Spec] = {}

    def register(self, spec: Spec) -> None:
        """Register a spec instance by its rule_id."""
        if spec.rule_id in self._registry:
            raise ValueError(f"Spec with rule_id '{spec.rule_id}' already registered")
        self._registry[spec.rule_id] = spec

    def register_many(self, specs: list[Spec]) -> None:
        """Register multiple specs."""
        for spec in specs:
            self.register(spec)

    def get(self, rule_id: str) -> Spec | None:
        """Get a registered spec by rule_id."""
        return self._registry.get(rule_id)

    def get_required(self, rule_id: str) -> Spec:
        """Get a registered spec, raising if not found."""
        spec = self.get(rule_id)
        if spec is None:
            raise KeyError(f"No spec registered with rule_id '{rule_id}'")
        return spec

    def evaluate(
        self,
        rule_ids: list[str],
        context: "Context",
        candidate: Any = None
    ) -> list[SpecResult]:
        """
        Evaluate a list of specs by their rule_ids.

        Args:
            rule_ids: List of spec rule_ids to evaluate
            context: Current workflow context
            candidate: Optional output to validate

        Returns:
            List of SpecResults in same order as rule_ids
        """
        results = []
        for rule_id in rule_ids:
            spec = self.get(rule_id)
            if spec is None:
                # Missing spec is a failure
                results.append(SpecResult.fail(
                    rule_id=rule_id,
                    message=f"Spec '{rule_id}' not found in registry",
                    suggested_fix="Register the spec or remove from step config",
                    tags=("error", "config")
                ))
            else:
                try:
                    result = spec.evaluate(context, candidate)
                    results.append(result)
                except Exception as e:
                    # Spec threw exception - treat as failure
                    results.append(SpecResult.fail(
                        rule_id=rule_id,
                        message=f"Spec raised exception: {e}",
                        suggested_fix="Fix the spec implementation",
                        tags=("error", "exception"),
                        data={"exception": str(e), "exception_type": type(e).__name__}
                    ))
        return results

    def evaluate_specs(
        self,
        specs: list[Spec],
        context: "Context",
        candidate: Any = None
    ) -> list[SpecResult]:
        """
        Evaluate spec instances directly (without registry lookup).

        Args:
            specs: List of Spec instances
            context: Current workflow context
            candidate: Optional output to validate

        Returns:
            List of SpecResults
        """
        results = []
        for spec in specs:
            try:
                result = spec.evaluate(context, candidate)
                results.append(result)
            except Exception as e:
                results.append(SpecResult.fail(
                    rule_id=spec.rule_id,
                    message=f"Spec raised exception: {e}",
                    suggested_fix="Fix the spec implementation",
                    tags=("error", "exception"),
                    data={"exception": str(e), "exception_type": type(e).__name__}
                ))
        return results

    def all_passed(self, results: list[SpecResult]) -> bool:
        """Check if all results passed."""
        return all(r.passed for r in results)

    def get_failures(self, results: list[SpecResult]) -> list[SpecResult]:
        """Get only the failed results."""
        return [r for r in results if not r.passed]

    def get_suggested_fixes(self, results: list[SpecResult]) -> list[str]:
        """Get suggested fixes from failed results."""
        return [r.suggested_fix for r in results if not r.passed and r.suggested_fix]

    def list_registered(self) -> list[str]:
        """List all registered rule_ids."""
        return list(self._registry.keys())


# ─── COMMON SPEC IMPLEMENTATIONS ────────────────────────────────────────────


class HasDataField(Spec):
    """Check that a required field exists in context.data."""

    def __init__(self, field_name: str, tags: tuple[str, ...] = ("precondition", "data")):
        self._field_name = field_name
        self._tags = tags

    @property
    def rule_id(self) -> str:
        return f"has_field:{self._field_name}"

    @property
    def tags(self) -> tuple[str, ...]:
        return self._tags

    def evaluate(self, context: "Context", candidate: Any = None) -> SpecResult:
        if context.has_data(self._field_name):
            return SpecResult.ok(
                rule_id=self.rule_id,
                message=f"Field '{self._field_name}' is present",
                tags=self.tags
            )
        return SpecResult.fail(
            rule_id=self.rule_id,
            message=f"Missing required field: {self._field_name}",
            suggested_fix=f"Ensure previous step produces '{self._field_name}'",
            tags=self.tags,
            data={"missing_field": self._field_name}
        )


class HasArtifact(Spec):
    """Check that an artifact exists."""

    def __init__(self, artifact_path: str, tags: tuple[str, ...] = ("precondition", "artifact")):
        self._artifact_path = artifact_path
        self._tags = tags

    @property
    def rule_id(self) -> str:
        return f"has_artifact:{self._artifact_path}"

    @property
    def tags(self) -> tuple[str, ...]:
        return self._tags

    def evaluate(self, context: "Context", candidate: Any = None) -> SpecResult:
        if context.has_artifact(self._artifact_path):
            return SpecResult.ok(
                rule_id=self.rule_id,
                message=f"Artifact '{self._artifact_path}' exists",
                tags=self.tags
            )
        return SpecResult.fail(
            rule_id=self.rule_id,
            message=f"Missing artifact: {self._artifact_path}",
            suggested_fix=f"Ensure previous step produces artifact '{self._artifact_path}'",
            tags=self.tags,
            data={"missing_artifact": self._artifact_path}
        )


class BudgetNotExceeded(Spec):
    """Check that budget limits are not exceeded."""

    rule_id = "budget_not_exceeded"
    tags = ("invariant", "budget")

    def evaluate(self, context: "Context", candidate: Any = None) -> SpecResult:
        budgets = context.budgets

        if budgets.is_total_budget_exceeded():
            return SpecResult.fail(
                rule_id=self.rule_id,
                message=f"Total attempts ({budgets.get_total_attempts()}) >= max ({budgets.max_total_attempts})",
                suggested_fix="Stop workflow, review failures",
                tags=self.tags,
                data={
                    "total_attempts": budgets.get_total_attempts(),
                    "max_attempts": budgets.max_total_attempts
                }
            )

        if budgets.is_cost_exceeded():
            return SpecResult.fail(
                rule_id=self.rule_id,
                message=f"Cost (${budgets.current_cost:.2f}) >= max (${budgets.max_cost_dollars:.2f})",
                suggested_fix="Stop workflow, cost limit reached",
                tags=self.tags,
                data={
                    "current_cost": budgets.current_cost,
                    "max_cost": budgets.max_cost_dollars
                }
            )

        return SpecResult.ok(
            rule_id=self.rule_id,
            message="Budget within limits",
            tags=self.tags
        )


class CandidateNotNone(Spec):
    """Check that the candidate output is not None."""

    def __init__(self, rule_id: str = "candidate_not_none"):
        self._rule_id = rule_id

    @property
    def rule_id(self) -> str:
        return self._rule_id

    @property
    def tags(self) -> tuple[str, ...]:
        return ("postcondition", "output")

    def evaluate(self, context: "Context", candidate: Any = None) -> SpecResult:
        if candidate is not None:
            return SpecResult.ok(
                rule_id=self.rule_id,
                message="Output produced",
                tags=self.tags
            )
        return SpecResult.fail(
            rule_id=self.rule_id,
            message="No output produced (candidate is None)",
            suggested_fix="Ensure agent returns a value",
            tags=self.tags
        )


class CandidateHasAttribute(Spec):
    """Check that the candidate has a specific attribute."""

    def __init__(self, attribute: str, rule_id: str | None = None):
        self._attribute = attribute
        self._rule_id = rule_id or f"candidate_has:{attribute}"

    @property
    def rule_id(self) -> str:
        return self._rule_id

    @property
    def tags(self) -> tuple[str, ...]:
        return ("postcondition", "schema")

    def evaluate(self, context: "Context", candidate: Any = None) -> SpecResult:
        if candidate is None:
            return SpecResult.fail(
                rule_id=self.rule_id,
                message="No candidate to check",
                suggested_fix="Ensure agent produces output",
                tags=self.tags
            )

        if hasattr(candidate, self._attribute):
            return SpecResult.ok(
                rule_id=self.rule_id,
                message=f"Candidate has attribute '{self._attribute}'",
                tags=self.tags
            )

        return SpecResult.fail(
            rule_id=self.rule_id,
            message=f"Candidate missing attribute: {self._attribute}",
            suggested_fix=f"Ensure output includes '{self._attribute}'",
            tags=self.tags,
            data={"missing_attribute": self._attribute}
        )
