"""
Manifest - Workflow definition as data.

The Manifest is the source of truth for the workflow:
- Defines steps (agent + specs + retry policy)
- Defines edges (transitions between steps)
- Defines global invariants and budgets
- Is loaded from YAML/JSON (no workflow logic in code)

Key principle: Graph structure is in the manifest, not in specs.
Specs decide if edges are eligible; edges define possible paths.
"""

from dataclasses import dataclass, field
from typing import Any
from pathlib import Path
import yaml
import json


@dataclass(frozen=True)
class RetryPolicy:
    """
    Policy for retrying failed steps.

    Controls how many times a step can be retried and backoff timing.
    """

    max_attempts: int = 3
    backoff_seconds: float = 1.0
    backoff_multiplier: float = 2.0

    def get_backoff(self, attempt: int) -> float:
        """Calculate backoff time for given attempt number."""
        if attempt <= 1:
            return 0
        return self.backoff_seconds * (self.backoff_multiplier ** (attempt - 2))


@dataclass(frozen=True)
class Step:
    """
    A step in the workflow.

    A Step binds:
    - An agent to execute
    - Specs to enforce (pre/post/invariant/progress)
    - Tool allowlist
    - Retry policy
    """

    step_id: str
    agent_id: str
    pre_specs: tuple[str, ...] = ()
    post_specs: tuple[str, ...] = ()
    invariant_specs: tuple[str, ...] = ()
    progress_specs: tuple[str, ...] = ()
    tool_allowlist: tuple[str, ...] = ()
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    description: str = ""
    input_mapping: dict[str, str] | None = None  # Map context keys to agent input

    @classmethod
    def from_dict(cls, step_id: str, data: dict) -> "Step":
        """Create Step from dictionary (e.g., from YAML)."""
        retry_data = data.get("retry_policy", {})
        retry_policy = RetryPolicy(
            max_attempts=retry_data.get("max_attempts", 3),
            backoff_seconds=retry_data.get("backoff_seconds", 1.0),
            backoff_multiplier=retry_data.get("backoff_multiplier", 2.0),
        )

        return cls(
            step_id=step_id,
            agent_id=data.get("agent_id", ""),
            pre_specs=tuple(data.get("pre_specs", [])),
            post_specs=tuple(data.get("post_specs", [])),
            invariant_specs=tuple(data.get("invariant_specs", [])),
            progress_specs=tuple(data.get("progress_specs", [])),
            tool_allowlist=tuple(data.get("tool_allowlist", [])),
            retry_policy=retry_policy,
            description=data.get("description", ""),
            input_mapping=data.get("input_mapping"),
        )

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "step_id": self.step_id,
            "agent_id": self.agent_id,
            "pre_specs": list(self.pre_specs),
            "post_specs": list(self.post_specs),
            "invariant_specs": list(self.invariant_specs),
            "progress_specs": list(self.progress_specs),
            "tool_allowlist": list(self.tool_allowlist),
            "retry_policy": {
                "max_attempts": self.retry_policy.max_attempts,
                "backoff_seconds": self.retry_policy.backoff_seconds,
                "backoff_multiplier": self.retry_policy.backoff_multiplier,
            },
            "description": self.description,
            "input_mapping": self.input_mapping,
        }


@dataclass(frozen=True)
class Edge:
    """
    A transition between steps.

    Edges define the graph structure:
    - from_step: Source step
    - to_step: Target step (or "__complete__" / "__fail__")
    - when: Condition expression for this edge

    Conditions can reference:
    - post_ok: All post_specs passed
    - invariant_ok: All invariant_specs passed
    - passed("rule_id"): Specific spec passed
    - failed("rule_id"): Specific spec failed
    - has("field"): Context has data field
    - attempts("step_id") < N: Attempt count check
    """

    from_step: str
    to_step: str
    when: str
    priority: int = 0  # Higher priority edges are checked first

    @classmethod
    def from_dict(cls, data: dict) -> "Edge":
        """Create Edge from dictionary."""
        return cls(
            from_step=data.get("from_step", ""),
            to_step=data.get("to_step", ""),
            when=data.get("when", "true"),
            priority=data.get("priority", 0),
        )

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "from_step": self.from_step,
            "to_step": self.to_step,
            "when": self.when,
            "priority": self.priority,
        }


@dataclass(frozen=True)
class GlobalConfig:
    """
    Global workflow configuration.

    Defines:
    - Invariant specs that apply to all steps
    - Budget limits
    - Logging settings
    """

    invariant_specs: tuple[str, ...] = ()
    max_total_attempts: int = 50
    max_attempts_per_step: int = 3
    max_cost_dollars: float = 10.0
    start_step: str = ""
    logging_level: str = "INFO"
    trace_all: bool = True

    @classmethod
    def from_dict(cls, data: dict) -> "GlobalConfig":
        """Create GlobalConfig from dictionary."""
        budgets = data.get("budgets", {})
        return cls(
            invariant_specs=tuple(data.get("invariant_specs", [])),
            max_total_attempts=budgets.get("max_total_attempts", 50),
            max_attempts_per_step=budgets.get("max_attempts_per_step", 3),
            max_cost_dollars=budgets.get("max_cost_dollars", 10.0),
            start_step=data.get("start_step", ""),
            logging_level=data.get("logging", {}).get("level", "INFO"),
            trace_all=data.get("logging", {}).get("trace_all", True),
        )

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "invariant_specs": list(self.invariant_specs),
            "budgets": {
                "max_total_attempts": self.max_total_attempts,
                "max_attempts_per_step": self.max_attempts_per_step,
                "max_cost_dollars": self.max_cost_dollars,
            },
            "start_step": self.start_step,
            "logging": {"level": self.logging_level, "trace_all": self.trace_all},
        }


@dataclass
class Manifest:
    """
    Complete workflow manifest.

    The Manifest is loaded from YAML/JSON and contains:
    - Version information
    - Agent configurations
    - Spec configurations
    - Step definitions
    - Edge definitions
    - Global settings
    """

    manifest_version: str
    spec_version: str
    steps: dict[str, Step]
    edges: list[Edge]
    globals: GlobalConfig
    agent_configs: dict[str, dict[str, Any]] = field(default_factory=dict)
    spec_configs: dict[str, dict[str, Any]] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def get_step(self, step_id: str) -> Step | None:
        """Get a step by id."""
        return self.steps.get(step_id)

    def get_step_required(self, step_id: str) -> Step:
        """Get a step, raising if not found."""
        step = self.get_step(step_id)
        if step is None:
            raise KeyError(f"No step with id '{step_id}'")
        return step

    def get_edges_from(self, step_id: str) -> list[Edge]:
        """Get all edges originating from a step, sorted by priority."""
        edges = [e for e in self.edges if e.from_step == step_id]
        return sorted(edges, key=lambda e: -e.priority)  # Higher priority first

    def get_start_step(self) -> str:
        """Get the starting step id."""
        if self.globals.start_step:
            return self.globals.start_step
        # Default: first step in definition order
        if self.steps:
            return next(iter(self.steps.keys()))
        raise ValueError("No steps defined in manifest")

    def list_steps(self) -> list[str]:
        """List all step ids."""
        return list(self.steps.keys())

    def validate(self) -> list[str]:
        """
        Validate the manifest for consistency.

        Returns list of error messages (empty if valid).
        """
        errors = []

        # Check start step exists
        start = self.globals.start_step
        if start and start not in self.steps:
            errors.append(f"Start step '{start}' not found in steps")

        # Check all edge references are valid
        valid_targets = set(self.steps.keys()) | {"__complete__", "__fail__"}
        for edge in self.edges:
            if edge.from_step not in self.steps:
                errors.append(f"Edge from unknown step: {edge.from_step}")
            if edge.to_step not in valid_targets:
                errors.append(f"Edge to unknown step: {edge.to_step}")

        # Check all steps have valid agent references (will be validated at runtime)
        # Check for unreachable steps
        reachable = {self.get_start_step()} if self.steps else set()
        changed = True
        while changed:
            changed = False
            for edge in self.edges:
                if edge.from_step in reachable and edge.to_step not in reachable:
                    if edge.to_step in self.steps:
                        reachable.add(edge.to_step)
                        changed = True

        unreachable = set(self.steps.keys()) - reachable
        if unreachable:
            errors.append(f"Unreachable steps: {unreachable}")

        return errors

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "manifest_version": self.manifest_version,
            "spec_version": self.spec_version,
            "agents": self.agent_configs,
            "specs": self.spec_configs,
            "steps": {k: v.to_dict() for k, v in self.steps.items()},
            "edges": [e.to_dict() for e in self.edges],
            "globals": self.globals.to_dict(),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Manifest":
        """Create Manifest from dictionary."""
        steps = {}
        for step_id, step_data in data.get("steps", {}).items():
            steps[step_id] = Step.from_dict(step_id, step_data)

        edges = [Edge.from_dict(e) for e in data.get("edges", [])]

        globals_config = GlobalConfig.from_dict(data.get("globals", {}))

        return cls(
            manifest_version=data.get("manifest_version", "1.0"),
            spec_version=data.get("spec_version", "1.0"),
            steps=steps,
            edges=edges,
            globals=globals_config,
            agent_configs=data.get("agents", {}),
            spec_configs=data.get("specs", {}),
            metadata=data.get("metadata", {}),
        )


class ManifestLoader:
    """
    Loader for manifest files.

    Supports YAML and JSON formats.
    """

    @staticmethod
    def load(path: Path | str) -> Manifest:
        """Load manifest from file."""
        path = Path(path)

        if not path.exists():
            raise FileNotFoundError(f"Manifest file not found: {path}")

        content = path.read_text(encoding="utf-8")

        if path.suffix in (".yaml", ".yml"):
            data = yaml.safe_load(content)
        elif path.suffix == ".json":
            data = json.loads(content)
        else:
            # Try YAML first, then JSON
            try:
                data = yaml.safe_load(content)
            except yaml.YAMLError:
                data = json.loads(content)

        manifest = Manifest.from_dict(data)

        # Validate
        errors = manifest.validate()
        if errors:
            raise ValueError(f"Invalid manifest: {errors}")

        return manifest

    @staticmethod
    def load_string(content: str, format: str = "yaml") -> Manifest:
        """Load manifest from string."""
        if format == "yaml":
            data = yaml.safe_load(content)
        elif format == "json":
            data = json.loads(content)
        else:
            raise ValueError(f"Unknown format: {format}")

        manifest = Manifest.from_dict(data)

        errors = manifest.validate()
        if errors:
            raise ValueError(f"Invalid manifest: {errors}")

        return manifest

    @staticmethod
    def save(manifest: Manifest, path: Path | str, format: str = "yaml") -> None:
        """Save manifest to file."""
        path = Path(path)
        data = manifest.to_dict()

        if format == "yaml":
            content = yaml.dump(data, default_flow_style=False, sort_keys=False)
        elif format == "json":
            content = json.dumps(data, indent=2)
        else:
            raise ValueError(f"Unknown format: {format}")

        path.write_text(content, encoding="utf-8")
