"""Tests for the Context system — immutable state, budgets, and updates."""

from manifold.core.context import (
    Context,
    ContextUpdater,
    create_context,
    Artifact,
    Budgets,
    TraceEntry,
    SpecResultRef,
)
from datetime import datetime


class TestCreateContext:
    def test_creates_with_defaults(self):
        ctx = create_context(run_id="test-001")
        assert ctx.run_id == "test-001"
        assert ctx.data == {}
        assert ctx.artifacts == {}
        assert ctx.trace == ()
        assert ctx.budgets.max_total_attempts == 50
        assert ctx.budgets.max_attempts_per_step == 3
        assert ctx.budgets.max_cost_dollars == 10.0

    def test_creates_with_initial_data(self):
        ctx = create_context(run_id="test-002", initial_data={"input": "hello"})
        assert ctx.data == {"input": "hello"}
        assert ctx.has_data("input")
        assert not ctx.has_data("missing")

    def test_creates_with_custom_budgets(self):
        budgets = Budgets(max_total_attempts=10, max_cost_dollars=5.0)
        ctx = create_context(run_id="test-003", budgets=budgets)
        assert ctx.budgets.max_total_attempts == 10
        assert ctx.budgets.max_cost_dollars == 5.0


class TestContextImmutability:
    def test_patch_data_returns_new_context(self):
        ctx = create_context(run_id="test-imm", initial_data={"a": 1})
        new_ctx = ContextUpdater.patch_data(ctx, "b", 2)

        # Original unchanged
        assert "b" not in ctx.data
        # New context has both
        assert new_ctx.data == {"a": 1, "b": 2}

    def test_remove_data_returns_new_context(self):
        ctx = create_context(run_id="test-rm", initial_data={"a": 1, "b": 2})
        new_ctx = ContextUpdater.remove_data(ctx, "a")

        assert ctx.data == {"a": 1, "b": 2}
        assert new_ctx.data == {"b": 2}

    def test_patch_data_many(self):
        ctx = create_context(run_id="test-many")
        new_ctx = ContextUpdater.patch_data_many(ctx, {"x": 10, "y": 20})
        assert new_ctx.data == {"x": 10, "y": 20}
        assert ctx.data == {}


class TestBudgets:
    def test_default_budgets(self):
        b = Budgets()
        assert b.get_step_attempts("step1") == 0
        assert b.get_total_attempts() == 0
        assert not b.is_step_budget_exceeded("step1")
        assert not b.is_total_budget_exceeded()
        assert not b.is_cost_exceeded()

    def test_increment_attempt(self):
        b = Budgets(max_attempts_per_step=2)
        b2 = b.with_incremented_attempt("step1")
        b3 = b2.with_incremented_attempt("step1")

        assert b.get_step_attempts("step1") == 0
        assert b2.get_step_attempts("step1") == 1
        assert b3.get_step_attempts("step1") == 2
        assert b3.is_step_budget_exceeded("step1")

    def test_cost_tracking(self):
        b = Budgets(max_cost_dollars=1.0)
        b2 = b.with_added_cost(0.50)
        b3 = b2.with_added_cost(0.60)

        assert not b2.is_cost_exceeded()
        assert b3.is_cost_exceeded()
        assert b3.current_cost == 1.10

    def test_total_budget_exceeded(self):
        b = Budgets(max_total_attempts=2)
        b2 = b.with_incremented_attempt("step1").with_incremented_attempt("step2")
        assert b2.is_total_budget_exceeded()


class TestArtifact:
    def test_from_content_string(self):
        artifact = Artifact.from_content(
            path="output/result.json",
            content='{"status": "ok"}',
            created_by_step="process"
        )
        assert artifact.path == "output/result.json"
        assert artifact.created_by_step == "process"
        assert len(artifact.content_hash) == 64  # SHA-256 hex

    def test_from_content_bytes(self):
        artifact = Artifact.from_content(
            path="output/image.png",
            content=b"\x89PNG\r\n",
            created_by_step="generate"
        )
        assert artifact.path == "output/image.png"
        assert len(artifact.content_hash) == 64

    def test_same_content_same_hash(self):
        a1 = Artifact.from_content("a.txt", "hello", "step1")
        a2 = Artifact.from_content("b.txt", "hello", "step2")
        assert a1.content_hash == a2.content_hash

    def test_different_content_different_hash(self):
        a1 = Artifact.from_content("a.txt", "hello", "step1")
        a2 = Artifact.from_content("a.txt", "world", "step1")
        assert a1.content_hash != a2.content_hash


class TestContextWithArtifacts:
    def test_append_artifact(self):
        ctx = create_context(run_id="test-art")
        artifact = Artifact.from_content("out.json", "{}", "step1")
        new_ctx = ContextUpdater.append_artifact(ctx, artifact)

        assert not ctx.has_artifact("out.json")
        assert new_ctx.has_artifact("out.json")
        assert new_ctx.get_artifact("out.json") == artifact


class TestTraceEntry:
    def test_passed_when_all_specs_pass(self):
        entry = TraceEntry(
            timestamp=datetime.now(),
            step_id="step1",
            attempt=1,
            agent_output="result",
            tool_calls=(),
            spec_results=(
                SpecResultRef(rule_id="r1", passed=True, message="ok"),
                SpecResultRef(rule_id="r2", passed=True, message="ok"),
            )
        )
        assert entry.passed
        assert entry.failed_rules == []

    def test_failed_when_any_spec_fails(self):
        entry = TraceEntry(
            timestamp=datetime.now(),
            step_id="step1",
            attempt=1,
            agent_output="result",
            tool_calls=(),
            spec_results=(
                SpecResultRef(rule_id="r1", passed=True, message="ok"),
                SpecResultRef(rule_id="r2", passed=False, message="bad"),
            )
        )
        assert not entry.passed
        assert entry.failed_rules == ["r2"]
