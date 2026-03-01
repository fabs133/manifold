"""
OpenAI Chat Completion Agent wrapper.

Supports GPT-4, GPT-4o, GPT-3.5-turbo, etc.
"""

from manifold import Agent, AgentOutput, Context, ToolCall
from typing import Any
import os
import urllib.request
import urllib.parse
import json


class OpenAIChatAgent(Agent):
    """
    Agent wrapper for OpenAI chat completion models.

    Supports:
    - gpt-4o
    - gpt-4-turbo
    - gpt-4
    - gpt-3.5-turbo
    """

    def __init__(
        self,
        agent_id: str,
        model: str = "gpt-4o",
        temperature: float = 0.3,
        max_tokens: int | None = None,
        response_format: dict | None = None,
        system_prompt: str | None = None,
        api_key: str | None = None
    ):
        """
        Args:
            agent_id: Unique identifier for this agent
            model: OpenAI chat model
            temperature: Sampling temperature (0-2)
            max_tokens: Maximum tokens in response
            response_format: Optional response format (e.g., {"type": "json_object"})
            system_prompt: Optional system prompt
            api_key: OpenAI API key (defaults to OPENAI_API_KEY env var)
        """
        self._agent_id = agent_id
        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._response_format = response_format
        self._system_prompt = system_prompt
        self._api_key = api_key or os.getenv("OPENAI_API_KEY")

        if not self._api_key:
            raise ValueError("OpenAI API key required (set OPENAI_API_KEY env var)")

    @property
    def agent_id(self) -> str:
        return self._agent_id

    async def execute(self, context: Context, input_data: dict[str, Any] | None = None) -> AgentOutput:
        """
        Generate chat completion.

        Expects context.data to have:
        - user_message: User message text OR
        - messages: Full message history

        Returns:
            AgentOutput with assistant's message (string or parsed JSON)
        """
        # Build messages array
        messages = []

        # Add system prompt if configured
        if self._system_prompt:
            messages.append({
                "role": "system",
                "content": self._system_prompt
            })

        # Get user input from context
        if context.has_data("messages"):
            # Use full message history
            messages.extend(context.get_data("messages"))
        elif context.has_data("user_message"):
            # Simple user message
            messages.append({
                "role": "user",
                "content": context.get_data("user_message")
            })
        else:
            # Missing input - return None output
            return AgentOutput(
                output=None,
                tool_calls=[],
                cost=0.0
            )

        # Build request payload
        payload = {
            "model": self._model,
            "messages": messages,
            "temperature": self._temperature,
        }

        if self._max_tokens:
            payload["max_tokens"] = self._max_tokens

        if self._response_format:
            payload["response_format"] = self._response_format

        # Make API request
        url = "https://api.openai.com/v1/chat/completions"
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

            # Extract response
            message = result["choices"][0]["message"]["content"]
            usage = result.get("usage", {})

            # Parse JSON response if requested
            output = message
            if self._response_format and self._response_format.get("type") == "json_object":
                try:
                    output = json.loads(message)
                except json.JSONDecodeError:
                    # Return string if JSON parsing fails
                    pass

            # Calculate cost
            cost = self._calculate_cost(
                usage.get("prompt_tokens", 0),
                usage.get("completion_tokens", 0)
            )

            tool_call = ToolCall(
                name="openai_chat_completion",
                args={
                    "model": self._model,
                    "messages": len(messages),
                    "prompt_tokens": usage.get("prompt_tokens", 0)
                },
                result={
                    "completion_tokens": usage.get("completion_tokens", 0),
                    "finish_reason": result["choices"][0].get("finish_reason"),
                    "cost": cost
                },
                duration_ms=0
            )

            return AgentOutput(
                output=output,
                tool_calls=[tool_call],
                cost=cost
            )

        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8')
            # API error - return None output
            return AgentOutput(
                output=None,
                tool_calls=[],
                cost=0.0
            )

        except Exception as e:
            # Execution error - return None output
            return AgentOutput(
                output=None,
                tool_calls=[],
                cost=0.0
            )

    def _calculate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        """Calculate API cost based on token usage."""
        # Pricing as of 2024 (per 1M tokens)
        pricing = {
            "gpt-4o": (2.50, 10.00),  # (input, output) per 1M tokens
            "gpt-4o-mini": (0.15, 0.60),
            "gpt-4-turbo": (10.00, 30.00),
            "gpt-4": (30.00, 60.00),
            "gpt-3.5-turbo": (0.50, 1.50),
        }

        # Get pricing for model (default to gpt-4o)
        input_price, output_price = pricing.get(self._model, (2.50, 10.00))

        # Calculate cost
        input_cost = (prompt_tokens / 1_000_000) * input_price
        output_cost = (completion_tokens / 1_000_000) * output_price

        return input_cost + output_cost
