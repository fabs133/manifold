# Manifold
### Contract-Driven Orchestration for Multi-Agent AI Systems

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Scientific Paper on Zenodo](https://img.shields.io/badge/Zenodo-Scientific%20Paper-blue)](https://zenodo.org/records/18707311)
[![Status: Alpha](https://img.shields.io/badge/status-alpha-orange.svg)]()

> **600 trials. Standard prompting reported 100% success. Actual correct output: 34%.**  
> Manifold eliminates false positives entirely through external specification-driven validation.

---

## The Problem

Most agent frameworks put the agent in two roles at once: **executor and judge**.

It performs the task. Then it decides if its output is correct. This is like asking a student to grade their own exam. The result across 600 controlled trials:

| Approach | True Success | False Positives | Relative Cost |
|---|---|---|---|
| Naive prompting | 34% | **66%** | 1× |
| Retry logic | 38% | 62% | 1.5–3.5× |
| **Manifold** | **94%** | **0%** | **0.36×** |

Two failure modes drive this:

1. **Silent false positives** — the agent reports success, the output is wrong. Your system never finds out.
2. **Infinite retry loops** — output is bad → retry → same output → retry. Standard retry counters count attempts, not progress.

---

## The Solution

Manifold treats prompts as **contracts**, not instructions.

Each workflow step defines what must be true *before* it runs, what must be true *after*, what must always hold globally, and what must *change* before a retry is allowed. Verification is external — the agent's opinion about its own output is irrelevant.

```
Instruction approach:  agent executes → agent judges → system trusts
Manifold approach:     agent executes → spec engine judges → system trusts the spec
```

---

## Quick Start

```bash
pip install manifold-ai
```

### 1. Define Specs

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

### 2. Define Workflow (YAML)

```yaml
manifest_version: "1.0"
globals:
  start_step: "extract"
  budgets:
    max_total_attempts: 10
    max_attempts_per_step: 3
    max_cost_dollars: 5.0

steps:
  extract:
    agent_id: "extraction_agent"
    pre_specs:  ["has_api_key"]
    post_specs: ["output_not_empty"]

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

### 3. Run

```python
from manifold import OrchestratorBuilder

orchestrator = (
    OrchestratorBuilder()
    .with_manifest_file("workflow.yaml")
    .with_spec(HasAPIKey())
    .with_spec(OutputNotEmpty())
    .build()
)

result = await orchestrator.run(initial_data={"api_key": "sk-..."})

print(f"Success: {result.success}")
print(f"Steps executed: {result.total_steps_executed}")
print(f"Trace: {result.final_context.trace}")
```

---

## Core Concepts

### Four Spec Categories

| Category | Purpose |
|---|---|
| **Preconditions** | Must be true before the agent runs. Gates execution. |
| **Postconditions** | Must be true about the output. Eliminates false positives. |
| **Invariants** | Must always hold across the entire run. Global safety constraints. |
| **Progress conditions** | Must show the situation changed. Prevents infinite retry loops. |

### Semantic Loop Detection

Standard retry counters count attempts. Manifold counts *progress*.

```python
fingerprint = hash(step_id, canonical_inputs, tool_calls, failed_rule_ids, missing_fields)

if fingerprint in seen_fingerprints:
    raise LoopDetectedError()  # Blocked — not just counted
```

Every retry must represent genuine forward movement. Same situation = blocked.

### Declarative Manifests

Workflows live in data, not code. Swap domains by swapping manifests. Agents are replaceable components. Specs are the laws of physics.

---

## Comparison

| Feature | Manifold | LangGraph | Manual Code |
|---|---|---|---|
| Declarative manifests | ✓ | Partial | ✗ |
| External spec validation | ✓ | ✗ | Manual |
| Loop prevention | ✓ | ✗ | Manual |
| Progress conditions | ✓ | ✗ | Manual |
| Complete tracing | ✓ | Partial | Manual |
| Zero false positives | ✓ | ✗ | Manual |

---

## Research

This framework is the subject of a published whitepaper and accompanying scientific paper with full experimental methodology across 600 trials.

📄 **[Whitepaper — Architecture & Concepts](./manifold_whitepaper_v2.pdf)** *(this repo)*  
🔬 **[Scientific Paper — Full Methodology & Results on Zenodo](https://zenodo.org/records/18707311)** *(600 trials, statistical analysis)*

**Honest note on scope:** The experimental results come from controlled trials at a scale I could fund independently. I don't have the resources for large-scale production testing across diverse domains. If you stress-test this architecture and find failure modes — I want to know. Every independent result, including negative ones, advances the work.

Open to collaboration and co-authorship on follow-up research.

---

## When to Use Manifold

**Best fit:**
- Multi-step workflows with verifiable intermediate outputs
- Data extraction and format compliance tasks
- Production systems where silent failures are costly
- Any pipeline where you need to know *why* something failed

**Less applicable:**
- Purely creative tasks where "correct" is subjective
- Exploratory tasks with undefined output spaces

Even in creative domains, loop prevention and cost control provide value.

---

## Requirements

- Python 3.10+
- PyYAML

---

## Status

**Alpha (v0.1.0)** — Core architecture is stable. API may evolve.

Feedback, issues, and pull requests welcome.

---

## Contact

**Fabio-Eric Rempel** · [fabiorempel@proton.me](mailto:fabiorempel@proton.me) · [github.com/fabs133](https://github.com/fabs133)

---

*MIT License · Built on contract-driven design and immutable data patterns*
