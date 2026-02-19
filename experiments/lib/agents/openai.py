"""OpenAI Chat Agent — wraps the OpenAI Chat Completions API as a Manifold Agent."""

import json
import time
import urllib.request
from typing import Any

from manifold.core.agent import Agent, AgentOutput
from manifold.core.context import Context, ToolCall


class OpenAIChatAgent(Agent):
    """Agent that calls OpenAI Chat Completions and returns parsed JSON."""

    def __init__(
        self,
        agent_id: str,
        model: str = "gpt-4o",
        temperature: float = 0.0,
        system_prompt: str = "",
        api_key: str = "",
    ):
        self._agent_id = agent_id
        self._model = model
        self._temperature = temperature
        self._system_prompt = system_prompt
        self._api_key = api_key

    @property
    def agent_id(self) -> str:
        return self._agent_id

    @property
    def description(self) -> str:
        return f"OpenAI Chat Agent ({self._model})"

    async def execute(
        self, context: Context, input_data: dict[str, Any] | None = None
    ) -> AgentOutput:
        user_message = ""
        if input_data:
            user_message = input_data.get("user_message", "")
        if not user_message:
            user_message = context.data.get("user_message", "")

        start_ms = time.monotonic_ns() // 1_000_000

        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": self._system_prompt},
                {"role": "user", "content": user_message},
            ],
            "temperature": self._temperature,
            "response_format": {"type": "json_object"},
        }

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=120) as response:
            result = json.loads(response.read().decode("utf-8"))

        duration_ms = (time.monotonic_ns() // 1_000_000) - start_ms

        raw_content = result["choices"][0]["message"]["content"]
        usage = result.get("usage", {})
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        cost = (prompt_tokens / 1_000_000) * 2.50 + (
            completion_tokens / 1_000_000
        ) * 10.00

        try:
            output = json.loads(raw_content)
        except json.JSONDecodeError:
            output = {"error": "Failed to parse JSON", "raw": raw_content}

        tool_call = ToolCall(
            name="openai_chat_completions",
            args={"model": self._model, "temperature": self._temperature},
            result=output,
            duration_ms=duration_ms,
            cost=cost,
        )

        return AgentOutput(
            output=output,
            delta={"extracted": output},
            tool_calls=[tool_call],
            raw=raw_content,
            cost=cost,
        )
