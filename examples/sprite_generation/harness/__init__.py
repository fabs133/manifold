"""
Sprite generation harness for Manifold.

This harness wraps the sprite-pipeline hook system to work seamlessly
with Manifold orchestration while preserving all existing functionality.

Example usage:
    ```python
    from sprite_pipeline.providers.fast_hook_provider import FastHookProvider
    from manifold.harnesses.sprite import create_sprite_agents
    from manifold.harnesses.sprite.specs import (
        HasGlobalStyleSpec,
        PromptNotEmptySpec,
        ImageDimensionsSpec,
        GridLayoutValidSpec,
    )
    from manifold import OrchestratorBuilder

    # Create hook provider
    hook_provider = FastHookProvider()

    # Create sprite agents
    agents = create_sprite_agents(hook_provider)

    # Build orchestrator
    orchestrator = (
        OrchestratorBuilder()
        .with_manifest_file("sprite_manifest.yaml")
        .with_agent(agents["prompt_builder"])
        .with_agent(agents["brief_builder"])
        .with_agent(agents["sprite_generator"])
        .with_spec(HasGlobalStyleSpec())
        .with_spec(PromptNotEmptySpec())
        .with_spec(ImageDimensionsSpec())
        .with_spec(GridLayoutValidSpec())
        .build()
    )

    # Run workflow
    result = await orchestrator.run(initial_data={
        "spec": {...},
        "global_style": "Pixel Art",
    })
    ```
"""

from manifold.harnesses.sprite.agent import (
    SpriteGenerationAgent,
    PromptBuilderAgent,
    BriefBuilderAgent,
    create_sprite_agents,
)

from manifold.harnesses.sprite.specs import (
    ImageDimensionsSpec,
    SpriteExtractionSpec,
    GridLayoutValidSpec,
    HasGlobalStyleSpec,
    PromptNotEmptySpec,
)

__all__ = [
    # Agents
    "SpriteGenerationAgent",
    "PromptBuilderAgent",
    "BriefBuilderAgent",
    "create_sprite_agents",
    # Specs
    "ImageDimensionsSpec",
    "SpriteExtractionSpec",
    "GridLayoutValidSpec",
    "HasGlobalStyleSpec",
    "PromptNotEmptySpec",
]
