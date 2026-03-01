"""
Sprite generation agent that wraps existing hook provider.

This adapter allows your existing sprite-pipeline hook system
to work seamlessly with Manifold orchestration.
"""

from manifold import Agent, AgentOutput, Context
from typing import Any, Optional
import asyncio


class SpriteGenerationAgent(Agent):
    """
    Agent that generates sprites using a hook provider.

    This wraps your existing FastHookProvider to work with Manifold.
    The hook provider handles the actual GPT image generation.
    """

    def __init__(self, hook_provider: Any):
        """
        Initialize with a hook provider.

        Args:
            hook_provider: Instance with async run(HookRequest) method
                          (e.g., FastHookProvider from sprite-pipeline)
        """
        self._provider = hook_provider

    @property
    def agent_id(self) -> str:
        return "sprite_generator"

    @property
    def description(self) -> str:
        return "Generates sprite images using GPT image models"

    async def execute(
        self, context: Context, input_data: dict[str, Any] | None = None
    ) -> AgentOutput:
        """
        Generate sprite image.

        Expected context.data:
        - prompt_text: The generated prompt
        - gen_size: Image size (default: "1024x1024")

        Returns:
            AgentOutput with image metadata and PNG bytes
        """
        # Import here to avoid circular dependency
        from sprite_pipeline.hooks import HookRequest, HookTaskType

        prompt = context.get_data("prompt_text", "")
        gen_size = context.get_data("gen_size", "1024x1024")

        if not prompt:
            return AgentOutput(output=None, delta={}, cost=0.0)

        # Create image generation request
        request = HookRequest(
            task_type=HookTaskType.GENERATE_IMAGE, prompt_text=prompt, gen_size=gen_size
        )

        # Call hook provider
        response = await self._provider.run(request)

        if response.status == "ok" and response.artifacts:
            artifact = response.artifacts[0]

            return AgentOutput(
                output={"width": artifact.width, "height": artifact.height, "status": "ok"},
                delta={
                    "generated_image": {
                        "width": artifact.width,
                        "height": artifact.height,
                        "size_bytes": len(artifact.png_bytes),
                    },
                    "image_bytes": artifact.png_bytes,
                },
                cost=0.04,  # Approximate GPT image generation cost
            )

        elif response.status == "content_policy":
            return AgentOutput(
                output={"status": "content_policy", "error": response.error_message},
                delta={"error": response.error_message},
                cost=0.0,
            )

        else:
            return AgentOutput(
                output={"status": "error", "error": response.error_message},
                delta={"error": response.error_message},
                cost=0.0,
            )


class PromptBuilderAgent(Agent):
    """
    Agent that builds sprite generation prompts.

    Wraps the BUILD_PROMPT hook to generate optimized prompts.
    """

    def __init__(self, hook_provider: Any):
        self._provider = hook_provider

    @property
    def agent_id(self) -> str:
        return "prompt_builder"

    @property
    def description(self) -> str:
        return "Builds optimized prompts for sprite generation"

    async def execute(
        self, context: Context, input_data: dict[str, Any] | None = None
    ) -> AgentOutput:
        """
        Build sprite generation prompt.

        Expected context.data:
        - spec: Sprite specification (dict with category, rows, etc.)
        - global_style: Art style description

        Returns:
            AgentOutput with generated prompt text
        """
        from sprite_pipeline.hooks import HookRequest, HookTaskType

        spec = context.get_data("spec")
        global_style = context.get_data("global_style", "Pixel Art")

        if not spec:
            return AgentOutput(output="", delta={}, cost=0.0)

        request = HookRequest(
            task_type=HookTaskType.BUILD_PROMPT, spec=spec, global_style=global_style
        )

        response = await self._provider.run(request)

        if response.status == "ok" and response.text_output:
            return AgentOutput(
                output=response.text_output,
                delta={"prompt_text": response.text_output},
                cost=0.0,  # Prompt building is lightweight
            )

        return AgentOutput(
            output="", delta={"error": response.error_message or "Prompt build failed"}, cost=0.0
        )


class BriefBuilderAgent(Agent):
    """
    Agent that builds final generation briefs.

    Wraps the BUILD_BRIEF hook for grid-specific instructions.
    """

    def __init__(self, hook_provider: Any):
        self._provider = hook_provider

    @property
    def agent_id(self) -> str:
        return "brief_builder"

    @property
    def description(self) -> str:
        return "Builds grid-specific generation briefs"

    async def execute(
        self, context: Context, input_data: dict[str, Any] | None = None
    ) -> AgentOutput:
        """
        Build generation brief with grid constraints.

        Expected context.data:
        - spec: Sprite specification
        - global_style: Art style
        - prompt_text: Base prompt from PromptBuilderAgent

        Returns:
            AgentOutput with final brief text
        """
        from sprite_pipeline.hooks import HookRequest, HookTaskType

        spec = context.get_data("spec")
        global_style = context.get_data("global_style", "Pixel Art")
        prompt_text = context.get_data("prompt_text", "")

        request = HookRequest(
            task_type=HookTaskType.BUILD_BRIEF,
            spec=spec,
            global_style=global_style,
            prompt_text=prompt_text,
        )

        response = await self._provider.run(request)

        if response.status == "ok" and response.text_output:
            return AgentOutput(
                output=response.text_output, delta={"brief_text": response.text_output}, cost=0.0
            )

        return AgentOutput(
            output=prompt_text,  # Fallback to base prompt
            delta={"brief_text": prompt_text},
            cost=0.0,
        )


# Convenience function to create all sprite agents
def create_sprite_agents(hook_provider: Any) -> dict[str, Agent]:
    """
    Create all sprite-related agents.

    Args:
        hook_provider: Your FastHookProvider instance

    Returns:
        Dict mapping agent_id to Agent instance
    """
    return {
        "prompt_builder": PromptBuilderAgent(hook_provider),
        "brief_builder": BriefBuilderAgent(hook_provider),
        "sprite_generator": SpriteGenerationAgent(hook_provider),
    }
