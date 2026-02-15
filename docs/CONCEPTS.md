# Core Concepts

This document explains the foundational concepts of Manifold's architecture.

## Table of Contents

- [The Problem](#the-problem)
- [The Solution](#the-solution)
- [Core Components](#core-components)
- [Data Flow](#data-flow)
- [Design Principles](#design-principles)

---

## The Problem

Multi-agent AI systems fail in predictable ways:

### 1. Infinite Loops
Agents retry the same failing action indefinitely, wasting compute and money.

```python
# Broken retry logic
while not success:
    result = agent.execute()  # Fails with same error every time
    # No check if situation actually changed!
```

### 2. Blind Retries
Systems retry without fixing the root cause.

```python
# No validation
for attempt in range(3):
    result = call_api()
    if result:
        break
# What if the API key was missing all 3 times?
```

### 3. No Contract Enforcement
Outputs aren't validated before being passed to the next step.

```python
# Hope and pray
extracted_data = extract_agent.run(text)
# Is extracted_data valid? Has required fields? Unknown
process_agent.run(extracted_data)  # Might crash
```

### 4. Debugging Nightmares
No trace of why decisions were made or where failures occurred.

```python
# Black box
result = workflow.run()
# Failed. Why? Which step? What was the context? No idea.
```

---

## The Solution

Manifold enforces correctness through **declarative contracts**.

### Key Insight

> **Separate WHAT (graph structure) from WHEN (validation rules)**

- **Graph** = possible transitions (manifest data)
- **Specs** = constraints that gate transitions (pure functions)
- **Router** = selects which edge to take (condition evaluation)
- **Orchestrator** = enforces everything (execution engine)

---

## Core Components

See README.md for basic component overview. This document provides deep technical details.

---

## Design Principles

### 1. Contracts as Laws of Physics

Specs are **non-negotiable constraints**:
- Agent cannot run if pre-specs fail
- Output cannot be accepted if post-specs fail
- Workflow cannot continue if invariants fail

### 2. Separation of Concerns

- **Agents** = "what to do" (domain logic)
- **Specs** = "is it valid" (validation logic)
- **Manifest** = "what's possible" (graph structure)
- **Router** = "which way to go" (condition evaluation)

No component decides everything.

### 3. Immutability

Context is immutable → predictable, debuggable, thread-safe.

### 4. Traceability

Every decision is logged:
- What step ran
- What specs were evaluated
- What passed/failed
- What was the output
- What tools were called
- What was the routing decision

### 5. Fail-Fast with Suggested Fixes

Specs don't just say "failed" — they say **how to fix it**:
```python
SpecResult.fail(
    rule_id="missing_api_key",
    message="API key not found in context",
    suggested_fix="Set context.data['api_key'] = 'sk-...'"
)
```

This enables:
- Self-correction (agent can see suggested fix)
- Better debugging (humans know what to fix)
- Automated repair steps

### 6. Budget Enforcement

Prevent runaway costs:
- Max total attempts
- Max attempts per step
- Max cost in dollars

### 7. Progress-Based Retries

Retries only allowed if **situation changed**:
- New data retrieved
- Missing fields filled
- Different tools tried
- Fewer failing rules

---

## Next Steps

- [Manifest Schema Reference](MANIFEST_SCHEMA.md)
- [Writing Specs Guide](WRITING_SPECS.md)
- [Examples](../examples/)
