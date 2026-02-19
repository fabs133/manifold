"""Tests for the Router — edge condition evaluation and next-step selection."""

from datetime import datetime

from manifold.core.router import (
    ConditionEvaluator,
    Router,
    RetryRouter,
    COMPLETE,
    FAIL,
)
from manifold.core.context import (
    Context,
    TraceEntry,
    SpecResultRef,
    Budgets,
    create_context,
    ContextUpdater,
)
from manifold.core.manifest import Manifest, Step, Edge, GlobalConfig


def _make_trace_entry(
    step_id: str = "step1",
    spec_results: list[SpecResultRef] | None = None,
    error: str | None = None,
) -> TraceEntry:
    """Helper to create a TraceEntry with spec results."""
    return TraceEntry(
        timestamp=datetime.now(),
        step_id=step_id,
        attempt=1,
        agent_output=None,
        tool_calls=(),
        spec_results=tuple(spec_results or []),
        error=error,
    )


def _make_spec_ref(
    rule_id: str,
    passed: bool,
    tags: tuple[str, ...] = (),
    suggested_fix: str | None = None,
) -> SpecResultRef:
    """Helper to create a SpecResultRef."""
    return SpecResultRef(
        rule_id=rule_id,
        passed=passed,
        message="ok" if passed else "fail",
        tags=tags,
        suggested_fix=suggested_fix,
    )


class TestConditionEvaluator:
    """Test condition expression evaluation."""

    def test_literal_true(self):
        ctx = create_context("test")
        ev = ConditionEvaluator(ctx)
        assert ev.evaluate("true") is True
        assert ev.evaluate("True") is True
        assert ev.evaluate("  true  ") is True

    def test_literal_false(self):
        ctx = create_context("test")
        ev = ConditionEvaluator(ctx)
        assert ev.evaluate("false") is False
        assert ev.evaluate("False") is False

    def test_post_ok_no_trace(self):
        ctx = create_context("test")
        ev = ConditionEvaluator(ctx)
        assert ev.evaluate("post_ok") is True

    def test_post_ok_all_passed(self):
        ctx = create_context("test")
        trace = _make_trace_entry(spec_results=[
            _make_spec_ref("check1", True, tags=("postcondition",)),
            _make_spec_ref("check2", True, tags=("postcondition",)),
        ])
        ev = ConditionEvaluator(ctx, trace)
        assert ev.evaluate("post_ok") is True

    def test_post_ok_postcondition_failed(self):
        ctx = create_context("test")
        trace = _make_trace_entry(spec_results=[
            _make_spec_ref("check1", True, tags=("postcondition",)),
            _make_spec_ref("check2", False, tags=("postcondition",)),
        ])
        ev = ConditionEvaluator(ctx, trace)
        assert ev.evaluate("post_ok") is False

    def test_post_ok_non_postcondition_failure_ignored(self):
        ctx = create_context("test")
        trace = _make_trace_entry(spec_results=[
            _make_spec_ref("check1", True, tags=("postcondition",)),
            _make_spec_ref("invariant1", False, tags=("invariant",)),
        ])
        ev = ConditionEvaluator(ctx, trace)
        assert ev.evaluate("post_ok") is True

    def test_invariant_ok_all_passed(self):
        ctx = create_context("test")
        trace = _make_trace_entry(spec_results=[
            _make_spec_ref("inv1", True, tags=("invariant",)),
        ])
        ev = ConditionEvaluator(ctx, trace)
        assert ev.evaluate("invariant_ok") is True

    def test_invariant_ok_invariant_failed(self):
        ctx = create_context("test")
        trace = _make_trace_entry(spec_results=[
            _make_spec_ref("inv1", False, tags=("invariant",)),
        ])
        ev = ConditionEvaluator(ctx, trace)
        assert ev.evaluate("invariant_ok") is False

    def test_passed_function(self):
        ctx = create_context("test")
        trace = _make_trace_entry(spec_results=[
            _make_spec_ref("my_rule", True),
        ])
        ev = ConditionEvaluator(ctx, trace)
        assert ev.evaluate("passed('my_rule')") is True
        assert ev.evaluate("passed('other_rule')") is False

    def test_failed_function(self):
        ctx = create_context("test")
        trace = _make_trace_entry(spec_results=[
            _make_spec_ref("my_rule", False),
        ])
        ev = ConditionEvaluator(ctx, trace)
        assert ev.evaluate("failed('my_rule')") is True
        assert ev.evaluate("failed('unknown_rule')") is False

    def test_has_function(self):
        ctx = create_context("test", initial_data={"name": "Alice"})
        ev = ConditionEvaluator(ctx)
        assert ev.evaluate("has('name')") is True
        assert ev.evaluate("has('age')") is False

    def test_attempts_function(self):
        budgets = Budgets(current_attempts={"step1": 3})
        ctx = create_context("test", budgets=budgets)
        ev = ConditionEvaluator(ctx)
        assert ev.evaluate("attempts('step1') < 5") is True
        assert ev.evaluate("attempts('step1') >= 3") is True
        assert ev.evaluate("attempts('step1') < 3") is False
        assert ev.evaluate("attempts('step2') == 0") is True

    def test_compound_and(self):
        ctx = create_context("test", initial_data={"input": "data"})
        trace = _make_trace_entry(spec_results=[
            _make_spec_ref("check1", True, tags=("postcondition",)),
        ])
        ev = ConditionEvaluator(ctx, trace)
        assert ev.evaluate("post_ok and has('input')") is True
        assert ev.evaluate("post_ok and has('missing')") is False

    def test_compound_or(self):
        ctx = create_context("test")
        trace = _make_trace_entry(spec_results=[
            _make_spec_ref("check1", False, tags=("postcondition",)),
        ])
        ev = ConditionEvaluator(ctx, trace)
        # In compound expressions, use "True"/"False" (Python identifiers in eval context).
        # Lowercase "true"/"false" only works as standalone literals.
        assert ev.evaluate("post_ok or True") is True
        assert ev.evaluate("post_ok or False") is False

    def test_complex_retry_condition(self):
        budgets = Budgets(current_attempts={"generate_image": 2})
        ctx = create_context("test", budgets=budgets)
        trace = _make_trace_entry(spec_results=[
            _make_spec_ref("grid_layout_valid", False),
        ])
        ev = ConditionEvaluator(ctx, trace)
        assert ev.evaluate("failed('grid_layout_valid') and attempts('generate_image') < 5") is True
        assert ev.evaluate("failed('grid_layout_valid') and attempts('generate_image') < 2") is False

    def test_invalid_condition_returns_false(self):
        ctx = create_context("test")
        ev = ConditionEvaluator(ctx)
        assert ev.evaluate("this_is_not_valid_syntax!@#") is False

    def test_not_operator(self):
        ctx = create_context("test", initial_data={"x": 1})
        ev = ConditionEvaluator(ctx)
        assert ev.evaluate("not has('x')") is False
        assert ev.evaluate("not has('y')") is True


def _make_manifest(steps: dict[str, Step], edges: list[Edge], start_step: str = "") -> Manifest:
    """Helper to create a Manifest."""
    return Manifest(
        manifest_version="1.0",
        spec_version="1.0",
        steps=steps,
        edges=edges,
        globals=GlobalConfig(start_step=start_step),
    )


class TestRouter:
    """Test the Router's next-step selection logic."""

    def test_no_edges_returns_complete(self):
        manifest = _make_manifest(
            steps={"step1": Step(step_id="step1", agent_id="agent1")},
            edges=[],
        )
        router = Router(manifest)
        ctx = create_context("test")
        assert router.route("step1", ctx) == COMPLETE

    def test_true_edge_always_matches(self):
        manifest = _make_manifest(
            steps={"step1": Step(step_id="step1", agent_id="a1")},
            edges=[Edge(from_step="step1", to_step="__complete__", when="true")],
        )
        router = Router(manifest)
        ctx = create_context("test")
        assert router.route("step1", ctx) == COMPLETE

    def test_post_ok_routes_to_next(self):
        manifest = _make_manifest(
            steps={
                "step1": Step(step_id="step1", agent_id="a1"),
                "step2": Step(step_id="step2", agent_id="a2"),
            },
            edges=[
                Edge(from_step="step1", to_step="step2", when="post_ok", priority=10),
                Edge(from_step="step1", to_step="__fail__", when="true", priority=0),
            ],
        )
        router = Router(manifest)
        ctx = create_context("test")
        trace = _make_trace_entry(spec_results=[
            _make_spec_ref("check", True, tags=("postcondition",)),
        ])
        assert router.route("step1", ctx, trace) == "step2"

    def test_failed_spec_routes_to_retry(self):
        manifest = _make_manifest(
            steps={"gen": Step(step_id="gen", agent_id="a1")},
            edges=[
                Edge(from_step="gen", to_step="__complete__", when="post_ok", priority=10),
                Edge(from_step="gen", to_step="gen", when="failed('dims') and attempts('gen') < 3", priority=5),
                Edge(from_step="gen", to_step="__fail__", when="true", priority=0),
            ],
        )
        router = Router(manifest)
        budgets = Budgets(current_attempts={"gen": 1})
        ctx = create_context("test", budgets=budgets)
        trace = _make_trace_entry(spec_results=[
            _make_spec_ref("dims", False, tags=("postcondition",)),
        ])
        assert router.route("gen", ctx, trace) == "gen"

    def test_budget_exceeded_routes_to_fail(self):
        manifest = _make_manifest(
            steps={"gen": Step(step_id="gen", agent_id="a1")},
            edges=[
                Edge(from_step="gen", to_step="__complete__", when="post_ok", priority=10),
                Edge(from_step="gen", to_step="gen", when="failed('dims') and attempts('gen') < 3", priority=5),
                Edge(from_step="gen", to_step="__fail__", when="true", priority=0),
            ],
        )
        router = Router(manifest)
        budgets = Budgets(current_attempts={"gen": 5})
        ctx = create_context("test", budgets=budgets)
        trace = _make_trace_entry(spec_results=[
            _make_spec_ref("dims", False, tags=("postcondition",)),
        ])
        # attempts('gen') < 3 is False → fallback to "true" → __fail__
        assert router.route("gen", ctx, trace) == FAIL

    def test_priority_ordering(self):
        manifest = _make_manifest(
            steps={"s1": Step(step_id="s1", agent_id="a1")},
            edges=[
                Edge(from_step="s1", to_step="__fail__", when="true", priority=0),
                Edge(from_step="s1", to_step="__complete__", when="true", priority=10),
            ],
        )
        router = Router(manifest)
        ctx = create_context("test")
        # Higher priority (10) should be checked first
        assert router.route("s1", ctx) == COMPLETE

    def test_no_matching_edge_returns_fail(self):
        manifest = _make_manifest(
            steps={"s1": Step(step_id="s1", agent_id="a1")},
            edges=[
                Edge(from_step="s1", to_step="__complete__", when="false"),
            ],
        )
        router = Router(manifest)
        ctx = create_context("test")
        assert router.route("s1", ctx) == FAIL

    def test_get_eligible_edges(self):
        manifest = _make_manifest(
            steps={"s1": Step(step_id="s1", agent_id="a1")},
            edges=[
                Edge(from_step="s1", to_step="s2", when="true"),
                Edge(from_step="s1", to_step="s3", when="false"),
                Edge(from_step="s1", to_step="s4", when="true"),
            ],
        )
        router = Router(manifest)
        ctx = create_context("test")
        eligible = router.get_eligible_edges("s1", ctx)
        targets = [e.to_step for e in eligible]
        assert "s2" in targets
        assert "s4" in targets
        assert "s3" not in targets

    def test_explain_routing(self):
        manifest = _make_manifest(
            steps={"s1": Step(step_id="s1", agent_id="a1")},
            edges=[
                Edge(from_step="s1", to_step="__complete__", when="post_ok", priority=10),
                Edge(from_step="s1", to_step="__fail__", when="true", priority=0),
            ],
        )
        router = Router(manifest)
        ctx = create_context("test")
        trace = _make_trace_entry(spec_results=[
            _make_spec_ref("check", True, tags=("postcondition",)),
        ])
        explanation = router.explain_routing("s1", ctx, trace)
        assert explanation["current_step"] == "s1"
        assert explanation["selected_next"] == "__complete__"
        assert explanation["edges_evaluated"] == 2
        assert len(explanation["edge_details"]) == 2


class TestRetryRouter:
    """Test the specialized RetryRouter."""

    def test_should_not_retry_on_success(self):
        rr = RetryRouter(max_attempts_per_step=3)
        ctx = create_context("test")
        trace = _make_trace_entry(spec_results=[
            _make_spec_ref("check", True),
        ])
        assert rr.should_retry("step1", ctx, trace) is False

    def test_should_retry_on_recoverable_failure(self):
        rr = RetryRouter(max_attempts_per_step=3)
        ctx = create_context("test")
        trace = _make_trace_entry(spec_results=[
            _make_spec_ref("check", False, suggested_fix="Try again"),
        ])
        assert rr.should_retry("step1", ctx, trace) is True

    def test_should_not_retry_when_budget_exceeded(self):
        rr = RetryRouter(max_attempts_per_step=3)
        budgets = Budgets(current_attempts={"step1": 3})
        ctx = create_context("test", budgets=budgets)
        trace = _make_trace_entry(spec_results=[
            _make_spec_ref("check", False, suggested_fix="Try again"),
        ])
        assert rr.should_retry("step1", ctx, trace) is False

    def test_should_not_retry_without_suggested_fix(self):
        rr = RetryRouter(max_attempts_per_step=3)
        ctx = create_context("test")
        trace = _make_trace_entry(spec_results=[
            _make_spec_ref("check", False),
        ])
        assert rr.should_retry("step1", ctx, trace) is False

    def test_get_retry_info(self):
        rr = RetryRouter(max_attempts_per_step=5)
        budgets = Budgets(current_attempts={"step1": 2})
        ctx = create_context("test", budgets=budgets)
        trace = _make_trace_entry(spec_results=[
            _make_spec_ref("check1", False, suggested_fix="Fix it"),
            _make_spec_ref("check2", True),
        ])
        info = rr.get_retry_info("step1", ctx, trace)
        assert info["step_id"] == "step1"
        assert info["current_attempts"] == 2
        assert info["max_attempts"] == 5
        assert info["budget_remaining"] == 3
        assert info["failure_count"] == 1
        assert info["should_retry"] is True
