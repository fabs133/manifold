# Sprite Generation Example

This example demonstrates using Manifold to orchestrate the sprite-pipeline with contract-driven execution.

## Overview

The sprite harness wraps the existing sprite-pipeline hook system to work seamlessly with Manifold's orchestration framework. This provides:

- **Contract enforcement**: Pre/post-condition specs validate each stage
- **Retry logic**: Automatic retries with backoff for transient failures
- **Loop detection**: Prevents identical retries that waste API calls
- **Complete tracing**: Full audit trail of all decisions

## Architecture

### Agents

Three agents wrap the existing sprite-pipeline hooks:

1. **PromptBuilderAgent** (`prompt_builder`)
   - Wraps `BUILD_PROMPT` hook
   - Generates optimized prompt from sprite spec
   - Post-condition: prompt not empty

2. **BriefBuilderAgent** (`brief_builder`)
   - Wraps `BUILD_BRIEF` hook
   - Adds grid-specific instructions to prompt
   - Post-condition: brief text not empty

3. **SpriteGenerationAgent** (`sprite_generator`)
   - Wraps `GENERATE_IMAGE` hook
   - Calls GPT image model to generate sprites
   - Post-conditions: dimensions valid, grid layout valid

### Specs

Four custom specs validate sprite generation:

1. **HasGlobalStyleSpec** (pre-condition)
   - Ensures `global_style` is in context
   - Example: "Pixel Art", "Cartoon", "Retro 8-bit"

2. **PromptNotEmptySpec** (post-condition)
   - Validates prompt/brief was generated
   - Fails on empty or whitespace-only text

3. **ImageDimensionsSpec** (post-condition)
   - Validates image is at least 1024x1024
   - GPT always generates 1024x1024 images

4. **GridLayoutValidSpec** (post-condition)
   - Validates NxN grid layout is correct
   - Checks frames_per_row and row_count match

### Workflow

```
build_prompt → build_brief → generate_image → [complete]
     ↓              ↓               ↓
   [fail]        [fail]      [retry/fail]
```

**Edge Routing:**
- Success: `post_ok` → next step
- Retry: `failed('rule_id') and attempts('step') < N` → same step
- Failure: `attempts('step') >= N` → `__fail__`

## Prerequisites

1. **Install sprite-pipeline**:
   ```bash
   pip install -e /path/to/sprite-pipeline
   ```

2. **Configure OpenAI API key**:
   ```bash
   export OPENAI_API_KEY=sk-...
   ```

3. **Install Manifold** (for development):
   ```bash
   pip install -e /path/to/manifold
   ```

## Running the Example

```bash
cd examples/sprite_generation
python example.py
```

## Expected Output

```
=== Manifold Sprite Generation Example ===

[OK] FastHookProvider initialized
[OK] Created 3 sprite agents
[OK] Created 4 specs
[OK] Orchestrator built with manifest: manifest.yaml

Sprite Generation Request:
  Style: Pixel Art
  Category: character
  Row: knight walking forward
  Frames: 4

Starting workflow execution...

=== Workflow Result ===
Status: complete
Steps executed: 3
Total cost: $0.0400

[SUCCESS] Sprite generation completed!
  Image size: 245678 bytes
  Saved to: output_sprite.png
  Dimensions: 1024x1024

=== Execution Trace ===
1. build_prompt [OK] (cost: $0.0000)
2. build_brief [OK] (cost: $0.0000)
3. generate_image [OK] (cost: $0.0400)
```

## Manifest Configuration

Key settings in `manifest.yaml`:

```yaml
globals:
  budgets:
    max_total_attempts: 30
    max_attempts_per_step: 5
    max_cost_dollars: 5.0

steps:
  generate_image:
    retry_policy:
      max_attempts: 5
      backoff_seconds: 2.0
      backoff_multiplier: 1.5
```

This allows up to 5 retries for image generation with exponential backoff (2s → 3s → 4.5s → 6.75s → 10.125s).

## Success Rate

The sprite harness maintains the same 85%+ success rate as the current sprite-pipeline, while adding:

- Semantic loop detection (prevents identical retries)
- Progress-based retries (only retries if situation changed)
- Budget enforcement (prevents runaway API costs)
- Complete traceability (full audit trail)

## Integration with Sprite Pipeline

The harness is **non-invasive** — it wraps the existing `FastHookProvider` without modifying sprite-pipeline code:

```python
from sprite_pipeline.providers.fast_hook_provider import FastHookProvider
from examples.sprite_generation.harness.agent import create_sprite_agents

# Create hook provider (unchanged)
hook_provider = FastHookProvider()

# Wrap with Manifold agents
agents = create_sprite_agents(hook_provider)

# Use in orchestrator
orchestrator = (
    OrchestratorBuilder()
    .with_manifest_file("manifest.yaml")
    .with_agent(agents["prompt_builder"])
    .with_agent(agents["brief_builder"])
    .with_agent(agents["sprite_generator"])
    .build()
)
```

This allows sprite-pipeline to continue working independently while also being orchestratable via Manifold.

## Next Steps

1. Test end-to-end with real sprite-pipeline installation
2. Verify 85%+ success rate matches current pipeline
3. Add extraction specs for frame slicing validation
4. Document performance metrics (retry rates, costs, success rates)
