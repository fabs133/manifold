# Manifest Schema Reference

Complete reference for Manifold workflow manifest files (YAML/JSON).

## Table of Contents

- [Overview](#overview)
- [Manifest Structure](#manifest-structure)
- [Globals Section](#globals-section)
- [Steps Section](#steps-section)
- [Edges Section](#edges-section)
- [Complete Example](#complete-example)
- [Validation Rules](#validation-rules)

---

## Overview

A manifest is a declarative definition of your workflow:
- **What** can happen (graph structure)
- **When** it can happen (routing conditions)
- **How** to validate (spec references)

**Format:** YAML or JSON
**Location:** Loaded via `ManifestLoader.load("workflow.yaml")`

---

## Manifest Structure

```yaml
manifest_version: "1.0"      # Required: Manifest format version
spec_version: "1.0"          # Required: Spec format version

globals:                     # Required: Global configuration
  # ... see Globals Section

steps:                       # Required: Step definitions
  # ... see Steps Section

edges:                       # Required: Transition rules
  # ... see Edges Section
```

---

## Globals Section

Global configuration that applies to the entire workflow.

### Schema

```yaml
globals:
  start_step: string                    # Required: ID of starting step

  invariant_specs: [string]             # Optional: Specs that must always pass

  budgets:                              # Optional: Resource limits
    max_total_attempts: int             # Default: 50
    max_attempts_per_step: int          # Default: 3
    max_cost_dollars: float             # Default: 10.0

  logging:                              # Optional: Logging settings
    level: "DEBUG" | "INFO" | "WARNING" # Default: "INFO"
    trace_all: bool                     # Default: true
```

### Fields

#### `start_step` (required)
- **Type:** `string`
- **Description:** ID of the first step to execute
- **Example:** `"extract_data"`
- **Validation:** Must reference a step defined in `steps` section

#### `invariant_specs` (optional)
- **Type:** `list[string]`
- **Description:** Spec rule_ids that must pass at every step
- **Example:** `["budget_not_exceeded", "no_forbidden_tools"]`
- **Default:** `[]`
- **Use case:** Global constraints like budget limits, security policies

#### `budgets` (optional)
- **Type:** `object`
- **Description:** Resource limit configuration

##### `budgets.max_total_attempts`
- **Type:** `int`
- **Description:** Maximum total step attempts across entire workflow
- **Default:** `50`
- **Use case:** Prevent infinite loops at workflow level

##### `budgets.max_attempts_per_step`
- **Type:** `int`
- **Description:** Maximum attempts for any single step
- **Default:** `3`
- **Use case:** Step-level retry limit

##### `budgets.max_cost_dollars`
- **Type:** `float`
- **Description:** Maximum cost in USD
- **Default:** `10.0`
- **Use case:** Cost control for paid API calls

#### `logging` (optional)
- **Type:** `object`
- **Description:** Logging configuration

##### `logging.level`
- **Type:** `"DEBUG" | "INFO" | "WARNING" | "ERROR"`
- **Default:** `"INFO"`

##### `logging.trace_all`
- **Type:** `bool`
- **Default:** `true`
- **Description:** Whether to record complete trace entries

---

## Steps Section

Defines the workflow steps (nodes in the graph).

### Schema

```yaml
steps:
  step_id:                              # Required: Unique step identifier
    agent_id: string                    # Required: Agent to execute
    description: string                 # Optional: Human-readable description

    pre_specs: [string]                 # Optional: Pre-condition specs
    post_specs: [string]                # Optional: Post-condition specs
    invariant_specs: [string]           # Optional: Step-level invariants
    progress_specs: [string]            # Optional: Progress validation specs

    tool_allowlist: [string]            # Optional: Allowed tool names

    input_mapping:                      # Optional: Map context to agent input
      target_key: source_key

    retry_policy:                       # Optional: Retry configuration
      max_attempts: int                 # Default: 3
      backoff_seconds: float            # Default: 1.0
      backoff_multiplier: float         # Default: 2.0
```

### Fields

#### `agent_id` (required)
- **Type:** `string`
- **Description:** Unique identifier of the agent to execute
- **Example:** `"extraction_agent"`
- **Validation:** Must be registered with orchestrator via `with_agent()`

#### `description` (optional)
- **Type:** `string`
- **Description:** Human-readable description of step purpose
- **Example:** `"Extract structured data from input text"`

#### `pre_specs` (optional)
- **Type:** `list[string]`
- **Description:** Specs that must pass BEFORE step executes
- **Example:** `["has_input_file", "has_api_key"]`
- **Failure behavior:** Step not executed, workflow routes to recovery or fails

#### `post_specs` (optional)
- **Type:** `list[string]`
- **Description:** Specs that must pass for output to be ACCEPTED
- **Example:** `["output_not_empty", "valid_json", "has_required_fields"]`
- **Failure behavior:** Output rejected, step may retry or route to fix step

#### `invariant_specs` (optional)
- **Type:** `list[string]`
- **Description:** Step-level invariants (in addition to global invariants)
- **Example:** `["data_not_corrupted"]`
- **Failure behavior:** Workflow fails immediately

#### `progress_specs` (optional)
- **Type:** `list[string]`
- **Description:** Specs that verify situation changed since last attempt
- **Example:** `["new_data_retrieved", "missing_fields_filled"]`
- **Use case:** Anti-loop validation

#### `tool_allowlist` (optional)
- **Type:** `list[string]`
- **Description:** Names of tools this agent is allowed to call
- **Example:** `["read_file", "parse_json", "validate_schema"]`
- **Default:** `[]` (no tools allowed)
- **Validation:** Agent cannot call tools not in this list

#### `input_mapping` (optional)
- **Type:** `object (dict[string, string])`
- **Description:** Map context data keys to agent input keys
- **Example:**
  ```yaml
  input_mapping:
    file_path: input_file_path    # agent gets file_path from context.data.input_file_path
    api_key: openai_key            # agent gets api_key from context.data.openai_key
  ```
- **Use case:** Decouple agent interface from context structure

#### `retry_policy` (optional)
- **Type:** `object`
- **Description:** Retry behavior configuration

##### `retry_policy.max_attempts`
- **Type:** `int`
- **Default:** `3`
- **Description:** Maximum times to attempt this step

##### `retry_policy.backoff_seconds`
- **Type:** `float`
- **Default:** `1.0`
- **Description:** Initial backoff delay in seconds

##### `retry_policy.backoff_multiplier`
- **Type:** `float`
- **Default:** `2.0`
- **Description:** Multiplier for exponential backoff
- **Formula:** `delay = backoff_seconds * (backoff_multiplier ** (attempt - 1))`

---

## Edges Section

Defines transitions between steps (edges in the graph).

### Schema

```yaml
edges:
  - from_step: string                   # Required: Source step ID
    to_step: string                     # Required: Target step ID or terminal
    when: string                        # Required: Condition expression
    priority: int                       # Optional: Edge priority (default: 0)
```

### Fields

#### `from_step` (required)
- **Type:** `string`
- **Description:** ID of the step this edge originates from
- **Example:** `"extract_data"`
- **Validation:** Must reference a step defined in `steps` section

#### `to_step` (required)
- **Type:** `string`
- **Description:** ID of target step, or terminal state
- **Valid values:**
  - Any step ID from `steps` section
  - `"__complete__"` (workflow succeeded)
  - `"__fail__"` (workflow failed)
- **Example:** `"validate_output"` or `"__complete__"`

#### `when` (required)
- **Type:** `string`
- **Description:** Boolean condition expression
- **Evaluated:** After step executes, using context and spec results

##### Condition Primitives

| Primitive | Type | Description | Example |
|-----------|------|-------------|---------|
| `post_ok` | bool | All post-specs passed | `"post_ok"` |
| `invariant_ok` | bool | All invariants passed | `"invariant_ok"` |
| `passed("rule_id")` | bool | Specific spec passed | `"passed('valid_schema')"` |
| `failed("rule_id")` | bool | Specific spec failed | `"failed('missing_field')"` |
| `has("field")` | bool | Context has data field | `"has('customer_id')"` |
| `attempts("step_id")` | int | Attempt count for step | `"attempts('extract') < 3"` |
| `true` | bool | Always true | `"true"` |
| `false` | bool | Always false | `"false"` |

##### Operators

- **Logical:** `and`, `or`, `not`
- **Comparison:** `<`, `<=`, `>`, `>=`, `==`, `!=`
- **Grouping:** `(` and `)`

##### Examples

```yaml
# Simple success
when: "post_ok"

# Success with invariant check
when: "post_ok and invariant_ok"

# Specific failure handling
when: "failed('missing_api_key')"

# Retry with budget
when: "failed('network_error') and attempts('api_call') < 3"

# Complex condition
when: "has('extracted_data') and passed('valid_schema') and attempts('extract') < 5"

# Fallback (catch-all)
when: "true"
```

#### `priority` (optional)
- **Type:** `int`
- **Default:** `0`
- **Description:** Edge evaluation priority (higher = evaluated first)
- **Use case:** Ensure specific edges are checked before fallbacks

**Example:**
```yaml
edges:
  # High priority: specific success case
  - from_step: "extract"
    to_step: "validate"
    when: "post_ok and has('all_fields')"
    priority: 10

  # Medium priority: retry on specific failure
  - from_step: "extract"
    to_step: "lookup_missing"
    when: "failed('missing_fields') and attempts('extract') < 3"
    priority: 5

  # Low priority: fallback to failure
  - from_step: "extract"
    to_step: "__fail__"
    when: "attempts('extract') >= 3"
    priority: 1
```

---

## Complete Example

```yaml
manifest_version: "1.0"
spec_version: "1.0"

globals:
  start_step: "extract_data"

  invariant_specs:
    - "budget_not_exceeded"
    - "no_forbidden_tools"

  budgets:
    max_total_attempts: 20
    max_attempts_per_step: 3
    max_cost_dollars: 5.0

  logging:
    level: "INFO"
    trace_all: true

steps:
  extract_data:
    agent_id: "extraction_agent"
    description: "Extract structured data from input text"

    pre_specs:
      - "has_input_file"
      - "has_api_key"

    post_specs:
      - "output_not_empty"
      - "valid_json"
      - "has_required_fields"

    progress_specs:
      - "situation_changed"

    tool_allowlist:
      - "read_file"
      - "call_llm"
      - "parse_json"

    retry_policy:
      max_attempts: 3
      backoff_seconds: 1.0
      backoff_multiplier: 2.0

  lookup_missing_data:
    agent_id: "lookup_agent"
    description: "Retrieve missing fields from database"

    pre_specs:
      - "has_missing_fields_list"

    post_specs:
      - "filled_missing_fields"

    tool_allowlist:
      - "query_database"

  validate_output:
    agent_id: "validation_agent"
    description: "Final validation of extracted data"

    post_specs:
      - "all_fields_valid"
      - "no_duplicates"

edges:
  # Success path
  - from_step: "extract_data"
    to_step: "validate_output"
    when: "post_ok"
    priority: 10

  # Retry with missing data lookup
  - from_step: "extract_data"
    to_step: "lookup_missing_data"
    when: "failed('has_required_fields') and attempts('extract_data') < 3"
    priority: 5

  # Return to extraction after lookup
  - from_step: "lookup_missing_data"
    to_step: "extract_data"
    when: "post_ok"
    priority: 10

  # Final validation success
  - from_step: "validate_output"
    to_step: "__complete__"
    when: "post_ok"
    priority: 10

  # Failure cases
  - from_step: "extract_data"
    to_step: "__fail__"
    when: "attempts('extract_data') >= 3"
    priority: 1

  - from_step: "validate_output"
    to_step: "__fail__"
    when: "not post_ok"
    priority: 1
```

---

## Validation Rules

Manifold validates manifests on load:

### Structural Validation

1. **Required fields present**
   - `manifest_version`
   - `spec_version`
   - `globals.start_step`
   - `steps` (non-empty)
   - `edges` (non-empty)

2. **Start step exists**
   - `globals.start_step` must reference a defined step

3. **Edge references valid**
   - `from_step` must reference a defined step
   - `to_step` must reference a defined step or `__complete__` / `__fail__`

4. **No unreachable steps**
   - All steps must be reachable from `start_step` via edges
   - Warning: unreachable steps logged

### Runtime Validation

1. **Spec references**
   - All spec `rule_id` values must be registered with orchestrator
   - Missing specs cause runtime errors

2. **Agent references**
   - All `agent_id` values must be registered with orchestrator
   - Missing agents cause runtime errors

3. **Tool allowlist enforcement**
   - Agents cannot call tools not in their `tool_allowlist`
   - Violation triggers invariant failure

---

## Next Steps

- [Writing Specs Guide](WRITING_SPECS.md) - How to write custom specs
- [Core Concepts](CONCEPTS.md) - Architectural overview
- [Examples](../examples/) - Working examples
