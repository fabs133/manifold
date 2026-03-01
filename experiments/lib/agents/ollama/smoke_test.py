"""
Smoke test for OllamaAgent — verifies the agent works with Manifold
before running a full experiment.

Usage:
    cd C:\\Users\\fbrmp\\Projekte\\manifold
    python experiments/lib/agents/ollama/smoke_test.py
"""

import asyncio
import sys
from pathlib import Path

# Add repo root to path (5 levels up from experiments/lib/agents/ollama/)
_repo_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(_repo_root))
sys.path.insert(1, str(_repo_root / "experiments"))

from manifold import create_context
from lib.agents.ollama import OllamaAgent


SYSTEM_PROMPT = """
You are a classification assistant. Classify the given organization.
Return valid JSON with exactly these fields:
{
  "name": "organization name",
  "economic_orientation": "market" | "state" | "mixed" | "unknown",
  "cultural_orientation": "progressive" | "conservative" | "neutral" | "unknown",
  "sector": "ngo" | "think_tank" | "media" | "political" | "academic" | "other"
}
"""

TEST_CASES = [
    {
        "name": "Greenpeace Germany",
        "description": "International environmental NGO focused on climate action and anti-nuclear campaigns.",
        "expect_sector": "ngo",
    },
    {
        "name": "Konrad-Adenauer-Stiftung",
        "description": "Political foundation affiliated with the CDU, promotes Christian democratic values.",
        "expect_sector": "think_tank",
    },
    {
        "name": "Bertelsmann Stiftung",
        "description": "Operating foundation focused on education, healthcare, and social policy reform.",
        "expect_sector": "think_tank",
    },
]


async def run_smoke_test():
    agent = OllamaAgent(
        agent_id="ollama_classifier",
        model="qwen2.5:14b",
        temperature=0.0,
        json_mode=True,
        system_prompt=SYSTEM_PROMPT,
    )

    print(f"Smoke test: OllamaAgent with {agent._model}")
    print("=" * 60)

    passed = 0
    for tc in TEST_CASES:
        user_message = f"Organization: {tc['name']}\nDescription: {tc['description']}"

        context = create_context(
            run_id="smoke_test",
            initial_data={"user_message": user_message},
        )

        result = await agent.execute(context)

        # Check basics
        ok = (
            result.output is not None
            and isinstance(result.output, dict)
            and result.cost == 0.0
            and len(result.tool_calls) == 1
        )

        sector_match = (
            isinstance(result.output, dict)
            and result.output.get("sector") == tc["expect_sector"]
        )

        status = "PASS" if (ok and sector_match) else "FAIL"
        if ok and sector_match:
            passed += 1

        print(f"\n[{status}] {tc['name']}")
        if isinstance(result.output, dict):
            import json
            print(json.dumps(result.output, indent=2, ensure_ascii=False))
        else:
            print(f"  raw output: {result.output!r}")

        tc_entry = result.tool_calls[0] if result.tool_calls else None
        if tc_entry:
            print(f"  tokens: prompt={tc_entry.args.get('prompt_tokens')} "
                  f"completion={tc_entry.result.get('completion_tokens')}")
            if tc_entry.result.get("error"):
                print(f"  error: {tc_entry.result['error']}")

    print("\n" + "=" * 60)
    print(f"Result: {passed}/{len(TEST_CASES)} passed")

    if passed < len(TEST_CASES):
        print("\nNote: sector mismatches are model judgment calls, not bugs.")
        print("Check for None output or connection errors — those are real failures.")


if __name__ == "__main__":
    asyncio.run(run_smoke_test())
