"""
Ollama Chat Agent wrapper.

Supports any locally running Ollama model (qwen2.5:14b, mistral, etc.).
Drop-in replacement for OpenAIChatAgent — implements the same Agent ABC.

API docs: https://github.com/ollama/ollama/blob/main/docs/api.md#generate-a-chat-completion
"""

import json
import urllib.request
import urllib.error
from typing import Any

from manifold import Agent, AgentOutput, Context, ToolCall


class OllamaAgent(Agent):
    """
    Agent wrapper for locally running Ollama models.

    Structurally identical to OpenAIChatAgent — same message format,
    same JSON extraction logic — so experiments can swap backends
    without touching manifests or specs.

    Differences from OpenAI:
    - Endpoint: /api/chat instead of /v1/chat/completions
    - cost is always 0.0
    - JSON mode via "format": "json" instead of response_format
    - No streaming (stream=False)
    """

    def __init__(
        self,
        agent_id: str,
        model: str = "qwen2.5:14b",
        temperature: float = 0.0,
        max_tokens: int | None = None,
        json_mode: bool = False,
        system_prompt: str | None = None,
        base_url: str = "http://localhost:11434",
        timeout: int = 120,
    ):
        """
        Args:
            agent_id: Unique identifier for this agent instance
            model: Ollama model tag (e.g. "qwen2.5:14b", "mistral")
            temperature: Sampling temperature (0.0 = deterministic)
            max_tokens: Maximum tokens in response (None = model default)
            json_mode: If True, forces JSON output via Ollama's format param
            system_prompt: Optional system prompt prepended to messages
            base_url: Ollama server URL (default: localhost)
            timeout: HTTP request timeout in seconds
        """
        self._agent_id = agent_id
        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._json_mode = json_mode
        self._system_prompt = system_prompt
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    @property
    def agent_id(self) -> str:
        return self._agent_id

    @property
    def description(self) -> str:
        return f"Ollama agent using {self._model}"

    async def execute(
        self, context: Context, input_data: dict[str, Any] | None = None
    ) -> AgentOutput:
        """
        Run a chat completion via Ollama.

        Reads from context:
          - "messages": full message list (takes priority), OR
          - "user_message": single user string

        Returns AgentOutput with:
          - output: parsed dict if json_mode=True, else raw string
          - tool_calls: single ToolCall recording the request/response stats
          - cost: always 0.0
        """
        messages = self._build_messages(context)

        if not messages:
            return AgentOutput(output=None, tool_calls=[], cost=0.0)

        payload = self._build_payload(messages)

        raw_text, eval_count, prompt_eval_count, error = self._call_api(payload)

        if error:
            return AgentOutput(
                output=None,
                tool_calls=[self._make_tool_call(prompt_eval_count, eval_count, error=error)],
                cost=0.0,
            )

        output = self._parse_output(raw_text)

        return AgentOutput(
            output=output,
            raw=raw_text,
            tool_calls=[self._make_tool_call(prompt_eval_count, eval_count)],
            cost=0.0,
        )

    # ─── Private helpers ────────────────────────────────────────────────────

    def _build_messages(self, context: Context) -> list[dict]:
        messages = []

        if self._system_prompt:
            messages.append({"role": "system", "content": self._system_prompt})

        if context.has_data("messages"):
            messages.extend(context.get_data("messages"))
        elif context.has_data("user_message"):
            messages.append({"role": "user", "content": context.get_data("user_message")})

        return messages

    def _build_payload(self, messages: list[dict]) -> dict:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": self._temperature,
            },
        }

        if self._max_tokens is not None:
            payload["options"]["num_predict"] = self._max_tokens

        if self._json_mode:
            payload["format"] = "json"

        return payload

    def _call_api(
        self, payload: dict
    ) -> tuple[str | None, int, int, str | None]:
        """
        POST to Ollama /api/chat.

        Returns: (raw_text, eval_count, prompt_eval_count, error_message)
        """
        url = f"{self._base_url}/api/chat"
        data = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}

        try:
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                result = json.loads(resp.read().decode("utf-8"))

            raw_text = result.get("message", {}).get("content", "")
            eval_count = result.get("eval_count", 0)               # completion tokens
            prompt_eval_count = result.get("prompt_eval_count", 0) # prompt tokens
            return raw_text, eval_count, prompt_eval_count, None

        except urllib.error.URLError as e:
            return None, 0, 0, f"Connection error: {e.reason}"
        except Exception as e:
            return None, 0, 0, str(e)

    def _parse_output(self, raw_text: str | None) -> Any:
        """Parse output — JSON dict if json_mode, else raw string."""
        if not raw_text:
            return None

        if self._json_mode:
            try:
                return json.loads(raw_text)
            except json.JSONDecodeError:
                # Return string if model didn't comply (happens occasionally)
                return raw_text

        return raw_text

    def _make_tool_call(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        error: str | None = None,
    ) -> ToolCall:
        return ToolCall(
            name="ollama_chat",
            args={
                "model": self._model,
                "base_url": self._base_url,
                "prompt_tokens": prompt_tokens,
            },
            result={
                "completion_tokens": completion_tokens,
                "error": error,
            },
            duration_ms=0,
        )
