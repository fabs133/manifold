"""Tests for the Spec system — contracts, results, engine, and built-in specs."""

from manifold.core.spec import (
    Spec,
    SpecResult,
    SpecEngine,
    HasDataField,
    HasArtifact,
    BudgetNotExceeded,
    CandidateNotNone,
    CandidateHasAttribute,
)
from manifold.core.context import create_context, Artifact, Budgets, ContextUpdater


class TestSpecResult:
    def test_ok_result(self):
        result = SpecResult.ok("test_rule", "All good")
        assert result.passed
        assert result.rule_id == "test_rule"
        assert result.message == "All good"
        assert result.suggested_fix is None

    def test_fail_result(self):
        result = SpecResult.fail(
            "test_rule",
            "Something wrong",
            suggested_fix="Fix it"
        )
        assert not result.passed
        assert result.message == "Something wrong"
        assert result.suggested_fix == "Fix it"

    def test_ok_default_message(self):
        result = SpecResult.ok("rule1")
        assert result.message == "Passed"

    def test_result_with_tags(self):
        result = SpecResult.ok("rule1", tags=("critical", "format"))
        assert result.tags == ("critical", "format")

    def test_result_with_data(self):
        result = SpecResult.fail(
            "rule1",
            "Missing field",
            data={"missing_field": "email"}
        )
        assert result.data == {"missing_field": "email"}

    def test_to_dict(self):
        result = SpecResult.ok("rule1", "ok", tags=("tag1",))
        d = result.to_dict()
        assert d["rule_id"] == "rule1"
        assert d["passed"] is True
        assert d["tags"] == ["tag1"]


class TestCustomSpec:
    """Test creating custom specs (the primary user pattern)."""

    def test_simple_custom_spec(self):
        class HasEmail(Spec):
            @property
            def rule_id(self):
                return "has_email"

            def evaluate(self, context, candidate=None):
                if context.has_data("email"):
                    return SpecResult.ok(self.rule_id, "Email present")
                return SpecResult.fail(
                    self.rule_id,
                    "Missing email",
                    suggested_fix="Add email to context"
                )

        spec = HasEmail()
        assert spec.rule_id == "has_email"

        # Fails without email
        ctx = create_context("test")
        result = spec.evaluate(ctx)
        assert not result.passed
        assert result.suggested_fix == "Add email to context"

        # Passes with email
        ctx_with_email = create_context("test", initial_data={"email": "a@b.com"})
        result = spec.evaluate(ctx_with_email)
        assert result.passed


class TestBuiltInSpecs:
    def test_has_data_field_passes(self):
        spec = HasDataField(field_name="name")
        ctx = create_context("test", initial_data={"name": "Alice"})
        result = spec.evaluate(ctx)
        assert result.passed

    def test_has_data_field_fails(self):
        spec = HasDataField(field_name="name")
        ctx = create_context("test")
        result = spec.evaluate(ctx)
        assert not result.passed
        assert "name" in result.message

    def test_has_artifact_passes(self):
        spec = HasArtifact(artifact_path="output.json")
        ctx = create_context("test")
        artifact = Artifact.from_content("output.json", "{}", "step1")
        ctx = ContextUpdater.append_artifact(ctx, artifact)
        result = spec.evaluate(ctx)
        assert result.passed

    def test_has_artifact_fails(self):
        spec = HasArtifact(artifact_path="output.json")
        ctx = create_context("test")
        result = spec.evaluate(ctx)
        assert not result.passed

    def test_budget_not_exceeded_passes(self):
        spec = BudgetNotExceeded()
        ctx = create_context("test")
        result = spec.evaluate(ctx)
        assert result.passed

    def test_budget_not_exceeded_fails_on_cost(self):
        spec = BudgetNotExceeded()
        budgets = Budgets(max_cost_dollars=0.10, current_cost=0.50)
        ctx = create_context("test", budgets=budgets)
        result = spec.evaluate(ctx)
        assert not result.passed

    def test_candidate_not_none_passes(self):
        spec = CandidateNotNone()
        ctx = create_context("test")
        result = spec.evaluate(ctx, candidate={"data": "value"})
        assert result.passed

    def test_candidate_not_none_fails(self):
        spec = CandidateNotNone()
        ctx = create_context("test")
        result = spec.evaluate(ctx, candidate=None)
        assert not result.passed


class TestSpecEngine:
    def _make_engine(self):
        engine = SpecEngine()
        engine.register(HasDataField(field_name="input"))
        engine.register(CandidateNotNone())
        return engine

    def test_register_and_get(self):
        engine = self._make_engine()
        spec = engine.get("has_field:input")
        assert spec is not None

    def test_register_duplicate_raises(self):
        engine = SpecEngine()
        engine.register(HasDataField(field_name="x"))
        try:
            engine.register(HasDataField(field_name="x"))
            assert False, "Should have raised ValueError"
        except ValueError:
            pass

    def test_get_required_raises_on_missing(self):
        engine = SpecEngine()
        try:
            engine.get_required("nonexistent")
            assert False, "Should have raised KeyError"
        except KeyError:
            pass

    def test_evaluate_all_pass(self):
        engine = self._make_engine()
        ctx = create_context("test", initial_data={"input": "data"})
        results = engine.evaluate(["has_field:input"], ctx)
        assert len(results) == 1
        assert results[0].passed

    def test_evaluate_mixed_results(self):
        engine = self._make_engine()
        ctx = create_context("test")  # No "input" data
        results = engine.evaluate(["has_field:input"], ctx)
        assert len(results) == 1
        assert not results[0].passed
