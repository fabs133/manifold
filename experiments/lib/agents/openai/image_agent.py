"""
OpenAI Image Generation Agent wrapper.

Supports DALL-E 3 and gpt-image-1 models.
"""

from manifold import Agent, AgentOutput, Context, ToolCall
from typing import Any
import os
import urllib.request
import urllib.parse
import json
import base64
from io import BytesIO


class OpenAIImageAgent(Agent):
    """
    Agent wrapper for OpenAI image generation models.

    Supports:
    - dall-e-3
    - gpt-image-1

    Returns image metadata (URL, dimensions, base64 data).
    """

    def __init__(
        self,
        agent_id: str,
        model: str = "dall-e-3",
        size: str = "1024x1024",
        quality: str = "standard",
        api_key: str | None = None
    ):
        """
        Args:
            agent_id: Unique identifier for this agent
            model: OpenAI image model ("dall-e-3" or "gpt-image-1")
            size: Image size (default: "1024x1024")
            quality: Image quality ("standard" or "hd") - dall-e-3 only
            api_key: OpenAI API key (defaults to OPENAI_API_KEY env var)
        """
        self._agent_id = agent_id
        self._model = model
        self._size = size
        self._quality = quality
        self._api_key = api_key or os.getenv("OPENAI_API_KEY")

        if not self._api_key:
            raise ValueError("OpenAI API key required (set OPENAI_API_KEY env var)")

    @property
    def agent_id(self) -> str:
        return self._agent_id

    async def execute(self, context: Context, input_data: dict[str, Any] | None = None) -> AgentOutput:
        """
        Generate image using OpenAI API.

        Expects context.data to have:
        - prompt: Image generation prompt

        Returns:
            AgentOutput with image metadata dict:
            {
                "url": "https://...",
                "width": 1024,
                "height": 1024,
                "b64_data": "base64...",  # Optional
                "model": "dall-e-3",
                "cost": 0.04
            }
        """
        prompt = context.get_data("prompt")

        if not prompt:
            return AgentOutput(
                output=None,
                tool_calls=[],
                cost=0.0
            )

        # Build request payload
        payload = {
            "model": self._model,
            "prompt": prompt,
            "n": 1,
            "size": self._size,
        }

        # Model-specific params
        if self._model == "dall-e-3":
            payload["quality"] = self._quality
            payload["response_format"] = "url"  # or "b64_json"
        elif self._model == "gpt-image-1":
            # gpt-image-1 doesn't support quality/response_format
            pass

        # Make API request
        url = "https://api.openai.com/v1/images/generations"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json"
        }

        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode('utf-8'),
                headers=headers,
                method='POST'
            )

            with urllib.request.urlopen(req, timeout=120) as response:
                result = json.loads(response.read().decode('utf-8'))

            # Extract image data
            image_data = result["data"][0]
            image_url = image_data.get("url")

            # Download image to get dimensions and b64
            image_bytes = None
            if image_url:
                img_req = urllib.request.Request(image_url)
                with urllib.request.urlopen(img_req, timeout=30) as img_response:
                    image_bytes = img_response.read()

            # Parse dimensions from size parameter
            width, height = map(int, self._size.split('x'))

            # Build output
            output = {
                "url": image_url,
                "width": width,
                "height": height,
                "model": self._model,
                "cost": self._estimate_cost(),
            }

            if image_bytes:
                output["b64_data"] = base64.b64encode(image_bytes).decode('utf-8')
                output["size_bytes"] = len(image_bytes)

            tool_call = ToolCall(
                name="openai_image_generation",
                args={"model": self._model, "prompt": prompt[:100]},
                result={"url": image_url, "size": self._size},
                duration_ms=0  # Could track this if needed
            )

            return AgentOutput(
                output=output,
                tool_calls=[tool_call],
                cost=self._estimate_cost()
            )

        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8')
            # Return None to indicate failure (error can be logged in delta if needed)
            return AgentOutput(
                output=None,
                tool_calls=[],
                cost=0.0
            )

        except Exception as e:
            # Return None to indicate failure
            return AgentOutput(
                output=None,
                tool_calls=[],
                cost=0.0
            )

    def _estimate_cost(self) -> float:
        """Estimate API cost based on model and size."""
        # Pricing as of 2024
        if self._model == "dall-e-3":
            if self._quality == "hd" and self._size == "1024x1024":
                return 0.080
            elif self._quality == "hd":
                return 0.120  # 1024x1792 or 1792x1024
            else:
                return 0.040  # standard quality
        elif self._model == "gpt-image-1":
            return 0.040  # Same as dall-e-3 standard
        else:
            return 0.040  # Default estimate
