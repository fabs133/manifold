# Manifold

**Contract-Driven Orchestration for Multi-Agent AI Systems**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

Manifold enforces correctness in multi-agent workflows through declarative contracts and semantic loop prevention.

## The Problem

AI agents in production fail unpredictably:
- Loop indefinitely on the same error
- Retry blindly without fixing root causes
- Violate constraints and produce invalid outputs
- Make debugging impossible (no trace of decisions)

## The Solution

Manifold enforces correctness through contracts:

- **Specs** - Define what must be true (pre/post/invariant/progress)
- **Router** - Only valid transitions are possible (spec outcomes gate edges)
- **Loop Detection** - Semantic fingerprinting prevents duplicate failures
- **Tracing** - Every decision is logged with reasoning

Workflows are declarative YAML manifests. Agents are replaceable components. Contracts are the laws of physics.

## Quick Start

### Installation

```bash
pip install manifold-ai
```

### Example: Data Extraction Pipeline

**1. Define specs:**

```python
from manifold import Spec, SpecResult, Context

class HasAPIKey(Spec):
    rule_id = "has_api_key"
    tags = ("precondition", "config")

    def evaluate(self, context: Context, candidate=None):
        if context.has_data("api_key"):
            return SpecResult.ok(self.rule_id, "API key configured")
        return SpecResult.fail(
            self.rule_id,
            "Missing API key",
            suggested_fix="Set 'api_key' in context.data"
        )

class OutputNotEmpty(Spec):
    rule_id = "output_not_empty"
    tags = ("postcondition", "output")

    def evaluate(self, context: Context, candidate=None):
        if candidate and len(candidate) > 0:
            return SpecResult.ok(self.rule_id, f"Extracted {len(candidate)} items")
        return SpecResult.fail(
            self.rule_id,
            "No items extracted",
            suggested_fix="Check input data format or prompt"
        )
```

**2. Create manifest** (`workflow.yaml`):

```yaml
manifest_version: "1.0"
spec_version: "1.0"

globals:
  start_step: "extract"
  budgets:
    max_total_attempts: 10
    max_attempts_per_step: 3
    max_cost_dollars: 5.0

steps:
  extract:
    agent_id: "extraction_agent"
    pre_specs:
      - "has_api_key"
    post_specs:
      - "output_not_empty"
    retry_policy:
      max_attempts: 3
      backoff_seconds: 1.0

edges:
  - from_step: "extract"
    to_step: "__complete__"
    when: "post_ok"
    priority: 10

  - from_step: "extract"
    to_step: "__fail__"
    when: "attempts('extract') >= 3"
    priority: 1
```

**3. Run workflow:**

```python
from manifold import OrchestratorBuilder

orchestrator = (
    OrchestratorBuilder()
    .with_manifest_file("workflow.yaml")
    .with_spec(HasAPIKey())
    .with_spec(OutputNotEmpty())
    # .with_agent(your_agent)  # Add your agents
    .build()
)

result = await orchestrator.run(
    initial_data={"api_key": "sk-..."}
)

print(f"Success: {result.success}")
print(f"Steps executed: {result.total_steps_executed}")
print(f"Trace: {result.final_context.trace}")
```

## Core Concepts

### Specs (Specifications)

Pure validation functions that enforce contracts:

- **Pre-specs**: Must pass before step runs
- **Post-specs**: Must pass for output to be accepted
- **Invariant-specs**: Must always hold (global constraints)
- **Progress-specs**: Must show situation changed (anti-loop)

```python
@dataclass(frozen=True)
class SpecResult:
    rule_id: str
    passed: bool
    message: str
    suggested_fix: str | None = None
    tags: tuple[str, ...] = ()
    data: dict[str, Any] = field(default_factory=dict)
```

### Router

Evaluates edge conditions to determine next step:

```yaml
edges:
  - from_step: "generate"
    to_step: "validate"
    when: "post_ok"
    priority: 10

  - from_step: "generate"
    to_step: "retry_with_adjustment"
    when: "failed('quality_check') and attempts('generate') < 3"
    priority: 5
```

Condition primitives:
- `post_ok` - All post-specs passed
- `invariant_ok` - All invariant-specs passed
- `passed("rule_id")` - Specific spec passed
- `failed("rule_id")` - Specific spec failed
- `has("field")` - Context has data field
- `attempts("step_id") < N` - Attempt count check

### Loop Detection

Semantic fingerprinting prevents identical retries:

```python
fingerprint = hash(
    step_id,
    canonical_inputs,
    tool_calls,
    failed_rule_ids,
    missing_fields
)

if fingerprint in seen_fingerprints:
    raise LoopDetectedError()
```

### Tracing

Complete audit trail:

```python
@dataclass(frozen=True)
class TraceEntry:
    timestamp: datetime
    step_id: str
    attempt: int
    agent_output: Any
    tool_calls: tuple[ToolCall, ...]
    spec_results: tuple[SpecResultRef, ...]
    duration_ms: int
    error: str | None = None
```

## Features

- ✅ **Declarative Manifests** - Workflow as YAML/JSON data
- ✅ **Spec-Based Routing** - Conditions reference spec outcomes
- ✅ **Loop Prevention** - Semantic fingerprinting detects duplicates
- ✅ **Budget Enforcement** - Retry and cost limits
- ✅ **Complete Tracing** - Full audit trail of decisions
- ✅ **Immutable Context** - Predictable state management
- ✅ **Type-Safe** - Full mypy strict mode support
- ✅ **Zero Magic** - Explicit contracts, no hidden behavior

## Comparison

| Feature | Manifold | LangGraph | Manual Code |
|---------|----------|-----------|-------------|
| Declarative manifests | ✓ | Partial | ✗ |
| Loop prevention | ✓ | ✗ | Manual |
| Spec-based routing | ✓ | ✗ | Manual |
| Progress validation | ✓ | ✗ | Manual |
| Complete tracing | ✓ | Partial | Manual |

## Documentation

- [Core Concepts](docs/CONCEPTS.md)
- [Writing Specs](docs/WRITING_SPECS.md)
- [Manifest Schema](docs/MANIFEST_SCHEMA.md)
- [API Reference](docs/API.md)
- [Examples](manifold/examples/)

## Use Cases

- Multi-agent workflows with reliability requirements
- Production AI systems that need correctness guarantees
- Complex pipelines with retry/validation logic
- A/B testing different agent strategies
- Workflows where debugging is critical

## Requirements

- Python 3.10+
- PyYAML

## License

MIT License - see [LICENSE](LICENSE) for details

## Contributing

Contributions welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## Acknowledgments

Built on principles from:
- The Spec-Pattern Multi-Agent Architecture
- Contract-driven design
- Immutable data patterns

---

**Built by:** Fabio Rumpel  
**Status:** Alpha (v0.1.0)  
**Feedback:** Open an [issue](https://github.com/fabs133/manifold/issues)
