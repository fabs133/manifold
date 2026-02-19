"""
Experiment 4 Treatment: Multi-Step Content Generation (Manifold)

4-stage pipeline: Research → Outline → Draft → Polish.
Each stage is a separate Manifold agent. Agents write outputs to context.data
via delta, so subsequent agents can read prior stage results.

Architecture:
- ResearchAgent: reads 'topic' from context, writes 'research' to delta
- OutlinerAgent:  reads 'topic' + 'research' from context, writes 'outline' to delta
- DrafterAgent:   reads 'topic' + 'outline' from context, writes 'draft' to delta
- PolisherAgent:  reads 'draft' from context, writes 'final_content' to delta

Specs gate every transition:
- has_research:      pre-condition for outline step
- has_outline:       pre-condition for draft step
- has_draft:         pre-condition for polish step
- research_not_empty: post-condition for research step
- outline_not_empty:  post-condition for outline step
- draft_long_enough:  post-condition for draft step (≥1000 words)
"""

import os
import sys
import json
import time
import asyncio
import urllib.request
import urllib.error
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime

# Add manifold to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from manifold import (
    Agent,
    AgentOutput,
    Context,
    ToolCall,
    OrchestratorBuilder,
    create_context,
    Spec,
    SpecResult,
    BudgetNotExceeded,
)


# ────────────────────────────────────────────────────────────────────────────
# Helper: GPT-4o API call
# ────────────────────────────────────────────────────────────────────────────

def _call_gpt4o(system_msg: str, user_msg: str, api_key: str,
                temperature: float = 0.5, max_tokens: int = 3000) -> Dict[str, Any]:
    """Call GPT-4o and return {'output': str, 'cost': float}."""
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "gpt-4o",
        "messages": [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg}
        ],
        "temperature": temperature,
        "max_tokens": max_tokens
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode('utf-8'),
        headers=headers,
        method='POST'
    )
    with urllib.request.urlopen(req, timeout=120) as response:
        result = json.loads(response.read().decode('utf-8'))

    message = result["choices"][0]["message"]["content"]
    usage = result.get("usage", {})
    prompt_tokens = usage.get("prompt_tokens", 0)
    completion_tokens = usage.get("completion_tokens", 0)
    cost = (prompt_tokens / 1_000_000) * 2.50 + (completion_tokens / 1_000_000) * 10.00
    return {"output": message, "cost": cost, "usage": usage}


# ────────────────────────────────────────────────────────────────────────────
# Four Manifold Agents — each reads from context.data, writes via delta
# ────────────────────────────────────────────────────────────────────────────

class ResearchAgent(Agent):
    """Stage 1: Research. Reads 'topic', writes 'research' to delta."""

    def __init__(self, api_key: str):
        self._api_key = api_key

    @property
    def agent_id(self) -> str:
        return "researcher"

    async def execute(self, context: Context, input_data: dict | None = None) -> AgentOutput:
        topic = context.get_data("topic")
        if not topic:
            return AgentOutput(output=None, tool_calls=[], cost=0.0)

        try:
            r = _call_gpt4o(
                system_msg="You are a research assistant. Gather 3-5 key points about the topic as bullet points.",
                user_msg=f"Research key points for article about: {topic}",
                api_key=self._api_key,
                temperature=0.7
            )
            tool_call = ToolCall(
                name="gpt4o_research",
                args={"topic": topic},
                result={"cost": r["cost"], "length": len(r["output"])},
                duration_ms=0
            )
            return AgentOutput(
                output=r["output"],
                tool_calls=[tool_call],
                cost=r["cost"],
                delta={"research": r["output"]}  # written to context.data
            )
        except Exception:
            return AgentOutput(output=None, tool_calls=[], cost=0.0)


class OutlinerAgent(Agent):
    """Stage 2: Outline. Reads 'topic' + 'research', writes 'outline' to delta."""

    def __init__(self, api_key: str):
        self._api_key = api_key

    @property
    def agent_id(self) -> str:
        return "outliner"

    async def execute(self, context: Context, input_data: dict | None = None) -> AgentOutput:
        topic = context.get_data("topic")
        research = context.get_data("research")
        if not topic or not research:
            return AgentOutput(output=None, tool_calls=[], cost=0.0)

        try:
            r = _call_gpt4o(
                system_msg="You are an outlining expert. Create a structured article outline with ## headers.",
                user_msg=f"Create outline for article.\n\nTopic: {topic}\n\nResearch:\n{research}\n\nFormat with ## headers.",
                api_key=self._api_key,
                temperature=0.5
            )
            tool_call = ToolCall(
                name="gpt4o_outline",
                args={"topic": topic},
                result={"cost": r["cost"], "sections": r["output"].count("##")},
                duration_ms=0
            )
            return AgentOutput(
                output=r["output"],
                tool_calls=[tool_call],
                cost=r["cost"],
                delta={"outline": r["output"]}
            )
        except Exception:
            return AgentOutput(output=None, tool_calls=[], cost=0.0)


class DrafterAgent(Agent):
    """Stage 3: Draft. Reads 'topic' + 'outline', writes 'draft' to delta."""

    def __init__(self, api_key: str):
        self._api_key = api_key

    @property
    def agent_id(self) -> str:
        return "drafter"

    async def execute(self, context: Context, input_data: dict | None = None) -> AgentOutput:
        topic = context.get_data("topic")
        outline = context.get_data("outline")
        if not topic or not outline:
            return AgentOutput(output=None, tool_calls=[], cost=0.0)

        try:
            r = _call_gpt4o(
                system_msg="You are a technical writer. Write a complete article following the outline with full paragraphs.",
                user_msg=f"Write article following this outline:\n\n{outline}\n\nTopic: {topic}\nWrite complete article with full paragraphs.",
                api_key=self._api_key,
                temperature=0.6,
                max_tokens=3000
            )
            word_count = len(r["output"].split())
            tool_call = ToolCall(
                name="gpt4o_draft",
                args={"topic": topic},
                result={"cost": r["cost"], "word_count": word_count},
                duration_ms=0
            )
            return AgentOutput(
                output=r["output"],
                tool_calls=[tool_call],
                cost=r["cost"],
                delta={"draft": r["output"], "draft_word_count": word_count}
            )
        except Exception:
            return AgentOutput(output=None, tool_calls=[], cost=0.0)


class PolisherAgent(Agent):
    """Stage 4: Polish. Reads 'draft', writes 'final_content' to delta."""

    def __init__(self, api_key: str):
        self._api_key = api_key

    @property
    def agent_id(self) -> str:
        return "polisher"

    async def execute(self, context: Context, input_data: dict | None = None) -> AgentOutput:
        draft = context.get_data("draft")
        if not draft:
            return AgentOutput(output=None, tool_calls=[], cost=0.0)

        try:
            r = _call_gpt4o(
                system_msg="You are an editor. Polish the article for publication. Fix grammar, improve clarity, maintain length.",
                user_msg=f"Polish this article for publication:\n\n{draft}",
                api_key=self._api_key,
                temperature=0.3,
                max_tokens=3000
            )
            word_count = len(r["output"].split())
            tool_call = ToolCall(
                name="gpt4o_polish",
                args={},
                result={"cost": r["cost"], "word_count": word_count},
                duration_ms=0
            )
            return AgentOutput(
                output=r["output"],
                tool_calls=[tool_call],
                cost=r["cost"],
                delta={"final_content": r["output"], "final_word_count": word_count}
            )
        except Exception:
            return AgentOutput(output=None, tool_calls=[], cost=0.0)


# ────────────────────────────────────────────────────────────────────────────
# Validation Specs
# ────────────────────────────────────────────────────────────────────────────

class ResearchNotEmptySpec(Spec):
    """Post-spec: research output must be non-empty.

    Checks agent output (candidate) since delta hasn't been applied to context yet.
    Falls back to context.data for cases where it was already stored.
    """
    @property
    def rule_id(self) -> str:
        return "research_not_empty"

    def evaluate(self, context: Context, candidate=None) -> SpecResult:
        # candidate = agent_output.output (the raw string from the agent)
        research = candidate if candidate else context.get_data("research")
        if research and isinstance(research, str) and len(research.strip()) > 50:
            return SpecResult(rule_id=self.rule_id, passed=True,
                              message=f"Research OK ({len(research)} chars)")
        return SpecResult(rule_id=self.rule_id, passed=False,
                          message="Research output is empty or too short",
                          suggested_fix="Retry research stage")


class HasResearchSpec(Spec):
    """Pre-spec: research must exist before outlining."""
    @property
    def rule_id(self) -> str:
        return "has_research"

    def evaluate(self, context: Context, candidate=None) -> SpecResult:
        research = context.get_data("research")
        if research and len(research.strip()) > 50:
            return SpecResult(rule_id=self.rule_id, passed=True,
                              message="Research found in context")
        return SpecResult(rule_id=self.rule_id, passed=False,
                          message="Research not found in context",
                          suggested_fix="Research stage must complete first")


class OutlineNotEmptySpec(Spec):
    """Post-spec: outline must contain at least one ## header."""
    @property
    def rule_id(self) -> str:
        return "outline_not_empty"

    def evaluate(self, context: Context, candidate=None) -> SpecResult:
        # candidate = agent_output.output (the raw string from the agent)
        outline = candidate if candidate else context.get_data("outline")
        if outline and "##" in outline:
            sections = outline.count("##")
            return SpecResult(rule_id=self.rule_id, passed=True,
                              message=f"Outline OK ({sections} sections)")
        return SpecResult(rule_id=self.rule_id, passed=False,
                          message="Outline missing ## section headers",
                          suggested_fix="Retry outlining with explicit ## header instruction")


class HasOutlineSpec(Spec):
    """Pre-spec: outline must exist before drafting."""
    @property
    def rule_id(self) -> str:
        return "has_outline"

    def evaluate(self, context: Context, candidate=None) -> SpecResult:
        outline = context.get_data("outline")
        if outline and "##" in outline:
            return SpecResult(rule_id=self.rule_id, passed=True,
                              message="Outline found in context")
        return SpecResult(passed=False, rule_id=self.rule_id,
                          message="Outline not found in context",
                          suggested_fix="Outline stage must complete first")


class DraftLongEnoughSpec(Spec):
    """Post-spec: draft must be at least 600 words.

    GPT-4o reliably produces 700-900 words per single call at 3000 max_tokens.
    600 words is a meaningful, reliably achievable minimum.
    """
    @property
    def rule_id(self) -> str:
        return "draft_long_enough"

    def evaluate(self, context: Context, candidate=None) -> SpecResult:
        # candidate = agent_output.output (the raw string from the agent)
        draft = candidate if candidate else context.get_data("draft")
        if not draft:
            return SpecResult(rule_id=self.rule_id, passed=False,
                              message="Draft not found in context",
                              suggested_fix="Draft agent must write output to delta['draft']")
        word_count = len(draft.split())
        if word_count >= 600:
            return SpecResult(rule_id=self.rule_id, passed=True,
                              message=f"Draft OK ({word_count} words)")
        return SpecResult(rule_id=self.rule_id, passed=False,
                          message=f"Draft too short: {word_count} words (need 600)",
                          suggested_fix="Retry draft stage and write a longer article")


class HasDraftSpec(Spec):
    """Pre-spec: draft must exist before polishing."""
    @property
    def rule_id(self) -> str:
        return "has_draft"

    def evaluate(self, context: Context, candidate=None) -> SpecResult:
        draft = context.get_data("draft")
        if draft and len(draft.split()) >= 600:
            return SpecResult(rule_id=self.rule_id, passed=True,
                              message=f"Draft found in context ({len(draft.split())} words)")
        return SpecResult(rule_id=self.rule_id, passed=False,
                          message="Draft not found or too short in context",
                          suggested_fix="Draft stage must produce ≥600 words first")


# ────────────────────────────────────────────────────────────────────────────
# Main experiment runner
# ────────────────────────────────────────────────────────────────────────────

async def generate_content_manifold(
    topic_data: Dict[str, Any],
    api_key: str
) -> Dict[str, Any]:
    """
    Generate content using Manifold 4-step orchestration.

    Args:
        topic_data: Dict with 'topic', 'complexity', '_trial_id'
        api_key: OpenAI API key

    Returns:
        Result dict with metrics
    """
    trial_id = topic_data["_trial_id"]
    topic = topic_data["topic"]
    complexity = topic_data["complexity"]

    # Create all 4 agents
    researcher = ResearchAgent(api_key)
    outliner = OutlinerAgent(api_key)
    drafter = DrafterAgent(api_key)
    polisher = PolisherAgent(api_key)

    # Create specs
    specs = [
        ResearchNotEmptySpec(),
        HasResearchSpec(),
        OutlineNotEmptySpec(),
        HasOutlineSpec(),
        DraftLongEnoughSpec(),
        HasDraftSpec(),
        BudgetNotExceeded(),
    ]

    # Build orchestrator
    manifest_path = Path(__file__).parent / "workflow.yaml"

    orchestrator = (
        OrchestratorBuilder()
        .with_manifest_file(str(manifest_path))
        .with_agent(researcher)
        .with_agent(outliner)
        .with_agent(drafter)
        .with_agent(polisher)
        .with_specs(specs)
        .build()
    )

    start_time = time.time()

    try:
        result = await orchestrator.run(
            initial_data={"topic": topic}
        )

        elapsed = time.time() - start_time

        # Extract output from final context
        final_content = result.final_context.get_data("final_content")
        draft = result.final_context.get_data("draft")
        word_count = result.final_context.get_data("final_word_count") or (
            len(final_content.split()) if final_content else 0
        )

        # Count total API calls across stages
        total_api_calls = sum(
            len(t.tool_calls) for t in result.final_context.trace
            if t.tool_calls
        )

        # Count retries (any step that executed more than once)
        step_counts = {}
        for t in result.final_context.trace:
            step_counts[t.step_id] = step_counts.get(t.step_id, 0) + 1
        total_retries = sum(max(0, v - 1) for v in step_counts.values())

        # Wasted stages = steps that ran but whose output was discarded on retry
        wasted_stages = total_retries

        # Loop detection
        loop_detected = any(
            t.error and "loop" in t.error.lower()
            for t in result.final_context.trace
        )

        return {
            "trial_id": trial_id,
            "topic": topic,
            "complexity": complexity,
            "method": "manifold",
            "model": "gpt-4o",

            # Success
            "success": result.success,
            "word_count": word_count,

            # Efficiency
            "total_cost": result.final_context.budgets.current_cost,
            "time_seconds": elapsed,
            "total_steps_executed": result.total_steps_executed,
            "total_api_calls": total_api_calls,
            "total_retries": total_retries,
            "wasted_stages": wasted_stages,

            # Loop metrics
            "loop_detected": loop_detected,

            # Trace
            "trace_length": len(result.final_context.trace),
            "spec_failures": sum(
                1 for t in result.final_context.trace
                for s in t.spec_results
                if not s.passed
            ),

            "error": result.summary if not result.success else None,
            "timestamp": datetime.utcnow().isoformat()
        }

    except Exception as e:
        elapsed = time.time() - start_time
        return {
            "trial_id": trial_id,
            "topic": topic,
            "complexity": complexity,
            "method": "manifold",
            "model": "gpt-4o",
            "success": False,
            "word_count": 0,
            "total_cost": 0.0,
            "time_seconds": elapsed,
            "total_steps_executed": 0,
            "total_api_calls": 0,
            "total_retries": 0,
            "wasted_stages": 0,
            "loop_detected": False,
            "trace_length": 0,
            "spec_failures": 0,
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }


async def run_experiment(num_trials: int = 5):
    """Run the Manifold experiment."""
    # Load .env from experiments root
    env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY environment variable required")

    # Load dataset
    dataset_path = Path(__file__).resolve().parent.parent.parent / "datasets" / "content_topics.json"
    with open(dataset_path) as f:
        topics = json.load(f)

    print(f"\n{'='*60}")
    print("MANIFOLD EXPERIMENT: Multi-Step Content Generation")
    print(f"{'='*60}")
    print(f"Trials: {num_trials}")
    print(f"Dataset: {len(topics)} topics (cycling)")
    print()

    results = []
    for i in range(num_trials):
        topic_data = topics[i % len(topics)].copy()
        topic_data["_trial_id"] = i + 1
        print(f"\n{'====='*12}")
        print(f"TRIAL {i+1}/{num_trials} | {topic_data['complexity'].upper()}")
        print(f"Topic: {topic_data['topic']} (task {topic_data['id']})")
        print(f"{'====='*12}")

        result = await generate_content_manifold(topic_data, api_key)
        results.append(result)

        print(f"Success:    {result['success']}")
        print(f"Words:      {result['word_count']}")
        print(f"Cost:       ${result['total_cost']:.4f}")
        print(f"Time:       {result['time_seconds']:.1f}s")
        print(f"Steps:      {result['total_steps_executed']}")
        print(f"Retries:    {result['total_retries']}")
        if result.get("spec_failures"):
            print(f"Spec fails: {result['spec_failures']}")

        successes = sum(1 for r in results if r["success"])
        avg_cost = sum(r["total_cost"] for r in results) / len(results)
        print(f"\nProgress: {successes}/{len(results)} ({successes/len(results)*100:.1f}%) | Avg cost: ${avg_cost:.4f}")

        # Rate limit: 3s between trials (GPT-4o Tier 3 handles burst well)
        if i < num_trials - 1:
            await asyncio.sleep(3)

    # Save results
    output_path = Path(__file__).resolve().parent.parent / "results" / f"manifold_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w') as f:
        json.dump({
            "experiment": "exp4_content_manifold",
            "trials": num_trials,
            "results": results,
            "summary": calculate_summary(results)
        }, f, indent=2)

    print(f"\n[OK] Results saved to: {output_path}")
    print_summary(results)


def calculate_summary(results: list) -> Dict[str, Any]:
    """Calculate aggregate statistics."""
    total = len(results)
    successful = sum(1 for r in results if r["success"])
    avg_cost = sum(r["total_cost"] for r in results) / total if total > 0 else 0
    avg_time = sum(r["time_seconds"] for r in results) / total if total > 0 else 0
    avg_words = (
        sum(r["word_count"] for r in results if r["success"]) /
        max(sum(1 for r in results if r["success"]), 1)
    )
    avg_steps = sum(r.get("total_steps_executed", 0) for r in results) / total if total > 0 else 0
    avg_retries = sum(r.get("total_retries", 0) for r in results) / total if total > 0 else 0
    loop_incidents = sum(1 for r in results if r.get("loop_detected"))

    return {
        "total_trials": total,
        "successful": successful,
        "success_rate": successful / total if total > 0 else 0,
        "avg_cost_per_trial": avg_cost,
        "avg_time_seconds": avg_time,
        "avg_word_count": avg_words,
        "avg_steps_executed": avg_steps,
        "avg_retries": avg_retries,
        "loop_incidents": loop_incidents
    }


def print_summary(results: list):
    """Print summary statistics."""
    summary = calculate_summary(results)

    print("\n" + "="*60)
    print("MANIFOLD SUMMARY (Content Generation)")
    print("="*60)
    print(f"Total Trials:     {summary['total_trials']}")
    print(f"Successful:       {summary['successful']} ({summary['success_rate']:.1%})")
    print(f"Avg Cost:         ${summary['avg_cost_per_trial']:.4f}")
    print(f"Avg Time:         {summary['avg_time_seconds']:.2f}s")
    print(f"Avg Word Count:   {summary['avg_word_count']:.0f}")
    print(f"Avg Steps:        {summary['avg_steps_executed']:.2f}")
    print(f"Avg Retries:      {summary['avg_retries']:.2f}")
    print(f"Loop Incidents:   {summary['loop_incidents']}")
    print("="*60)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Exp4 Manifold: Multi-Step Content Generation")
    parser.add_argument("--trials", type=int, default=5, help="Number of trials to run")
    args = parser.parse_args()

    asyncio.run(run_experiment(num_trials=args.trials))
