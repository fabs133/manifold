"""
Sprite Generation Example using Manifold Orchestration.

This example demonstrates how to use Manifold to orchestrate the sprite
generation pipeline with contract-driven execution.

Prerequisites:
    - sprite-pipeline package installed
    - OpenAI API key configured
    - FastHookProvider available

Usage:
    python example.py
"""

import asyncio
import sys
from pathlib import Path

# Add manifold to path (for development)
manifold_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(manifold_root))

from manifold import (
    OrchestratorBuilder,
    create_context,
)

# Import sprite harness components
from manifold.harnesses.sprite.agent import create_sprite_agents
from manifold.harnesses.sprite.specs import (
    ImageDimensionsSpec,
    GridLayoutValidSpec,
    HasGlobalStyleSpec,
    PromptNotEmptySpec,
)


async def main():
    print("=== Manifold Sprite Generation Example ===\n")

    # 1. Create hook provider (from sprite-pipeline)
    # This assumes sprite_pipeline is installed
    try:
        from sprite_pipeline.providers.fast_hook_provider import FastHookProvider
        hook_provider = FastHookProvider()
        print("[OK] FastHookProvider initialized")
    except ImportError:
        print("[ERROR] sprite-pipeline not found. Install it first:")
        print("  pip install -e /path/to/sprite-pipeline")
        return

    # 2. Create sprite agents from harness
    agents = create_sprite_agents(hook_provider)
    print(f"[OK] Created {len(agents)} sprite agents")

    # 3. Create specs
    specs = [
        HasGlobalStyleSpec(),
        PromptNotEmptySpec(),
        ImageDimensionsSpec(min_width=1024, min_height=1024),
        GridLayoutValidSpec(),
    ]
    print(f"[OK] Created {len(specs)} specs")

    # 4. Build orchestrator
    manifest_path = Path(__file__).parent / "manifest.yaml"

    builder = OrchestratorBuilder().with_manifest_file(str(manifest_path))

    # Register agents
    for agent in agents.values():
        builder = builder.with_agent(agent)

    # Register specs
    for spec in specs:
        builder = builder.with_spec(spec)

    orchestrator = builder.build()
    print(f"[OK] Orchestrator built with manifest: {manifest_path.name}\n")

    # 5. Define sprite generation request
    spec = {
        "category": "character",
        "rows": [
            {
                "prompt": "knight walking forward",
                "variation_count": 4,
            }
        ],
        "frames_per_row": 4,
    }

    initial_data = {
        "spec": spec,
        "global_style": "Pixel Art",
        "gen_size": "1024x1024",
    }

    print("Sprite Generation Request:")
    print(f"  Style: {initial_data['global_style']}")
    print(f"  Category: {spec['category']}")
    print(f"  Row: {spec['rows'][0]['prompt']}")
    print(f"  Frames: {spec['frames_per_row']}")
    print()

    # 6. Run workflow
    print("Starting workflow execution...\n")

    result = await orchestrator.run(initial_data=initial_data)

    # 7. Display results
    print("\n=== Workflow Result ===")
    print(f"Status: {result.status}")
    print(f"Steps executed: {len(result.trace)}")
    print(f"Total cost: ${result.total_cost:.4f}")
    print()

    if result.status == "complete":
        print("[SUCCESS] Sprite generation completed!")

        # Check for generated image
        final_context = result.final_context
        if final_context and "image_bytes" in final_context.data:
            image_data = final_context.data["image_bytes"]
            print(f"  Image size: {len(image_data)} bytes")

            # Save to file
            output_path = Path(__file__).parent / "output_sprite.png"
            output_path.write_bytes(image_data)
            print(f"  Saved to: {output_path}")

        if final_context and "generated_image" in final_context.data:
            img_info = final_context.data["generated_image"]
            print(f"  Dimensions: {img_info['width']}x{img_info['height']}")

    else:
        print("[FAILED] Workflow did not complete successfully")

        if result.final_context and result.final_context.trace:
            last_entry = result.final_context.trace[-1]
            print(f"  Last step: {last_entry.step_id}")

            # Show failed specs
            failed_specs = [sr for sr in last_entry.spec_results if not sr.passed]
            if failed_specs:
                print("  Failed specs:")
                for sr in failed_specs:
                    print(f"    - {sr.rule_id}: {sr.message}")

    # 8. Show trace
    print("\n=== Execution Trace ===")
    for i, entry in enumerate(result.trace, 1):
        status = "OK" if all(sr.passed for sr in entry.spec_results) else "FAIL"
        print(f"{i}. {entry.step_id} [{status}] (cost: ${entry.cost:.4f})")


if __name__ == "__main__":
    asyncio.run(main())
