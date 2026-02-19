"""Tests for the Manifest system — loading, validation, and data structures."""

import json
import tempfile
import os

from manifold.core.manifest import (
    ManifestLoader,
    Manifest,
    Step,
    Edge,
    RetryPolicy,
    GlobalConfig,
)


class TestRetryPolicy:
    def test_defaults(self):
        policy = RetryPolicy()
        assert policy.max_attempts == 3
        assert policy.backoff_seconds == 1.0
        assert policy.backoff_multiplier == 2.0

    def test_backoff_first_attempt_is_zero(self):
        policy = RetryPolicy(backoff_seconds=2.0, backoff_multiplier=1.5)
        assert policy.get_backoff(1) == 0

    def test_backoff_second_attempt(self):
        policy = RetryPolicy(backoff_seconds=2.0, backoff_multiplier=1.5)
        assert policy.get_backoff(2) == 2.0

    def test_backoff_third_attempt(self):
        policy = RetryPolicy(backoff_seconds=2.0, backoff_multiplier=1.5)
        assert policy.get_backoff(3) == 3.0  # 2.0 * 1.5^1


class TestStep:
    def test_step_defaults(self):
        step = Step(step_id="extract", agent_id="extractor")
        assert step.step_id == "extract"
        assert step.agent_id == "extractor"
        assert step.pre_specs == ()
        assert step.post_specs == ()
        assert step.retry_policy.max_attempts == 3

    def test_step_with_specs(self):
        step = Step(
            step_id="validate",
            agent_id="validator",
            pre_specs=("has_input",),
            post_specs=("output_valid", "no_hallucination"),
        )
        assert len(step.pre_specs) == 1
        assert len(step.post_specs) == 2

    def test_step_from_dict(self):
        data = {
            "agent_id": "extractor",
            "post_specs": ["output_valid"],
            "retry_policy": {"max_attempts": 5},
        }
        step = Step.from_dict("extract", data)
        assert step.step_id == "extract"
        assert step.agent_id == "extractor"
        assert step.post_specs == ("output_valid",)
        assert step.retry_policy.max_attempts == 5


class TestEdge:
    def test_edge_from_dict(self):
        data = {
            "from_step": "process",
            "to_step": "__complete__",
            "when": "post_ok",
            "priority": 10,
        }
        edge = Edge.from_dict(data)
        assert edge.from_step == "process"
        assert edge.to_step == "__complete__"
        assert edge.when == "post_ok"
        assert edge.priority == 10


class TestGlobalConfig:
    def test_from_dict_with_budgets(self):
        data = {"budgets": {"max_total_attempts": 20, "max_cost_dollars": 5.0}}
        config = GlobalConfig.from_dict(data)
        assert config.max_total_attempts == 20
        assert config.max_cost_dollars == 5.0

    def test_defaults(self):
        config = GlobalConfig.from_dict({})
        assert config.max_total_attempts == 50
        assert config.max_cost_dollars == 10.0


class TestManifest:
    def _minimal_manifest_dict(self):
        """Manifest dict matching the actual API format (steps as dict)."""
        return {
            "globals": {"budgets": {"max_total_attempts": 20, "max_cost_dollars": 5.0}},
            "steps": {"process": {"agent_id": "processor", "post_specs": ["output_valid"]}},
            "edges": [{"from_step": "process", "to_step": "__complete__", "when": "post_ok"}],
        }

    def test_from_dict(self):
        manifest = Manifest.from_dict(self._minimal_manifest_dict())
        assert isinstance(manifest, Manifest)
        assert "process" in manifest.steps
        assert manifest.steps["process"].agent_id == "processor"

    def test_global_config_loaded(self):
        manifest = Manifest.from_dict(self._minimal_manifest_dict())
        assert manifest.globals.max_total_attempts == 20
        assert manifest.globals.max_cost_dollars == 5.0

    def test_edges_loaded(self):
        manifest = Manifest.from_dict(self._minimal_manifest_dict())
        complete_edges = [e for e in manifest.edges if e.to_step == "__complete__"]
        assert len(complete_edges) >= 1
        assert complete_edges[0].when == "post_ok"

    def test_get_step(self):
        manifest = Manifest.from_dict(self._minimal_manifest_dict())
        step = manifest.get_step("process")
        assert step is not None
        assert step.agent_id == "processor"
        assert manifest.get_step("nonexistent") is None

    def test_get_start_step(self):
        manifest = Manifest.from_dict(self._minimal_manifest_dict())
        assert manifest.get_start_step() == "process"

    def test_validate_valid_manifest(self):
        manifest = Manifest.from_dict(self._minimal_manifest_dict())
        errors = manifest.validate()
        assert errors == []


class TestManifestLoader:
    def _write_temp_json(self, data):
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
        return path

    def _minimal_manifest_dict(self):
        return {
            "globals": {"budgets": {"max_total_attempts": 20, "max_cost_dollars": 5.0}},
            "steps": {"process": {"agent_id": "processor", "post_specs": ["output_valid"]}},
            "edges": [{"from_step": "process", "to_step": "__complete__", "when": "post_ok"}],
        }

    def test_load_from_json_file(self):
        path = self._write_temp_json(self._minimal_manifest_dict())
        try:
            manifest = ManifestLoader.load(path)
            assert isinstance(manifest, Manifest)
            assert "process" in manifest.steps
        finally:
            os.unlink(path)

    def test_load_string_json(self):
        data = json.dumps(self._minimal_manifest_dict())
        manifest = ManifestLoader.load_string(data, format="json")
        assert isinstance(manifest, Manifest)
        assert manifest.steps["process"].agent_id == "processor"
