"""
Experiment 4 Smart Control: Engineered Content Generation Pipeline

Represents what a competent engineer would build:
- Multi-stage pipeline with validation between stages
- Smart recovery (retry from last good stage, not full restart)
- Quality checks at each stage
- Structured prompts for each stage

This is the REAL comparison for Manifold's orchestration value.
"""

import os
import sys
import json
import time
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime

# Add shared utilities
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from shared.validation_utils import ContentValidator


@dataclass
class StageResult:
    """Result of a pipeline stage."""
    success: bool
    output: Optional[str]
    errors: List[str]


class SmartContentPipeline:
    """
    Smart baseline: engineered content pipeline with stage validation.

    Key innovation: Validates each stage before proceeding.
    If stage N fails, retry just that stage (not full restart).

    This shows what good manual engineering achieves, setting
    the bar that Manifold must beat.
    """

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.validator = ContentValidator()

    def _research_stage(self, topic: str) -> StageResult:
        """Stage 1: Research with validation."""
        system_msg = """You are a research assistant.

Task: Gather key points for an article.

Requirements:
- Find 3-5 main points
- Include relevant examples
- Cite sources (general references OK)
- Format as bullet points"""

        prompt = f"Research key points for article about: {topic}"

        try:
            response_content = self._call_gpt4o(system_msg, prompt, temperature=0.7)
            output = response_content

            # Validate
            errors = []
            if len(output) < 200:
                errors.append("research_too_short")
            if '-' not in output and '•' not in output and '*' not in output:
                errors.append("research_no_bullet_points")

            lines_with_content = [l for l in output.split('\n') if l.strip() and len(l) > 20]
            if len(lines_with_content) < 3:
                errors.append("research_too_few_points")

            success = len(errors) == 0
            return StageResult(success, output if success else None, errors)

        except Exception as e:
            return StageResult(False, None, [f"research_error:{str(e)[:50]}"])

    def _outline_stage(self, topic: str, research: str) -> StageResult:
        """Stage 2: Outline with structural validation."""
        system_msg = """You are an outlining expert.

Task: Create article outline.

Requirements:
- Introduction section
- 3-5 main body sections
- Conclusion section
- Each section has 2-3 sub-points
- Logical flow
- Use ## markdown headers"""

        prompt = f"""Create outline for article.

Topic: {topic}

Research:
{research}

Format with ## headers for main sections."""

        try:
            response_content = self._call_gpt4o(system_msg, prompt, temperature=0.5)
            output = response_content

            # Validate structure
            errors = []

            # Check for intro/conclusion
            lower_output = output.lower()
            has_intro = 'introduction' in lower_output or 'intro' in lower_output
            has_conclusion = 'conclusion' in lower_output

            if not has_intro:
                errors.append("outline_no_intro")
            if not has_conclusion:
                errors.append("outline_no_conclusion")

            # Count sections
            section_headers = [line for line in output.split('\n') if line.strip().startswith('##')]
            body_sections = len(section_headers) - 2  # Exclude intro/conclusion

            if body_sections < 3:
                errors.append(f"outline_too_few_sections:{body_sections}")
            elif body_sections > 7:
                errors.append(f"outline_too_many_sections:{body_sections}")

            # Check for sub-points
            if output.count('-') < 5 and output.count('•') < 5 and output.count('*') < 5:
                errors.append("outline_no_subpoints")

            success = len(errors) == 0
            return StageResult(success, output if success else None, errors)

        except Exception as e:
            return StageResult(False, None, [f"outline_error:{str(e)[:50]}"])

    def _draft_stage(self, topic: str, outline: str, target_length: int = 1800) -> StageResult:
        """Stage 3: Draft with length and structure validation."""
        system_msg = """You are a technical writer.

Task: Write article following outline.

Requirements:
- Follow outline structure exactly
- Target length: 1000-2000 words
- Professional but accessible tone
- Complete sentences and paragraphs
- If technical topic, include concrete examples"""

        prompt = f"""Write article following this outline:

{outline}

Topic: {topic}
Target length: {target_length} words

Write complete article with full paragraphs."""

        try:
            response_content = self._call_gpt4o(system_msg, prompt, temperature=0.6, max_tokens=3000)
            output = response_content

            # Validate
            errors = []

            # Length check — 1000 min to accommodate GPT-4o realistic output
            word_count = len(output.split())
            if word_count < 1000:
                errors.append(f"draft_too_short:{word_count}w")
            elif word_count > 2500:
                errors.append(f"draft_too_long:{word_count}w")

            # Structure check - does it follow outline?
            outline_headers = [
                line.strip().replace('#', '').strip()
                for line in outline.split('\n')
                if line.strip().startswith('##')
            ]

            missing_sections = []
            for header in outline_headers:
                # Fuzzy matching - check if section title appears
                header_lower = header.lower()
                if header_lower not in output.lower():
                    missing_sections.append(header)

            if len(missing_sections) > 1:  # Allow 1 missing section
                errors.append(f"draft_missing_sections:{len(missing_sections)}")

            # Completeness check
            if output.count('.') < 30:  # Should have many sentences
                errors.append("draft_incomplete_sentences")

            success = len(errors) == 0
            return StageResult(success, output if success else None, errors)

        except Exception as e:
            return StageResult(False, None, [f"draft_error:{str(e)[:50]}"])

    def _polish_stage(self, draft: str) -> StageResult:
        """Stage 4: Polish with quality validation."""
        system_msg = """You are an editor.

Task: Polish article for publication.

Requirements:
- Fix grammar and spelling
- Improve clarity and flow
- Remove redundancy
- Maintain length (±100 words max)
- Keep technical accuracy
- Improve paragraph transitions"""

        prompt = f"""Polish this article for publication:

{draft}

Fix grammar, improve clarity, maintain length."""

        try:
            response_content = self._call_gpt4o(system_msg, prompt, temperature=0.3, max_tokens=3000)
            output = response_content

            # Validate
            errors = []

            # Length shouldn't change drastically
            original_words = len(draft.split())
            polished_words = len(output.split())
            word_diff = abs(polished_words - original_words)

            if word_diff > 300:
                errors.append(f"polish_length_change:{original_words}→{polished_words}")

            # Should still have structure
            if output.count('\n\n') < draft.count('\n\n') - 3:
                errors.append("polish_lost_structure")

            # Basic quality checks
            if len(output) < len(draft) * 0.8:
                errors.append("polish_too_much_cut")

            success = len(errors) == 0
            return StageResult(success, output if success else None, errors)

        except Exception as e:
            return StageResult(False, None, [f"polish_error:{str(e)[:50]}"])

    def generate(
        self,
        topic: str,
        target_length: int = 1800,
        max_stage_retries: int = 2
    ) -> Dict:
        """
        Generate content with smart pipeline recovery.

        Key feature: If stage N fails, retry just that stage.
        Track wasted work (stages that succeeded but were discarded).
        """
        start_time = time.time()

        result = {
            'success': False,
            'final_content': None,
            'word_count': 0,
            'total_cost': 0.0,
            'time_seconds': 0.0,
            'stage_attempts': {},
            'wasted_stages': 0,
            'stage_history': []
        }

        # Pipeline state
        research = None
        outline = None
        draft = None
        final = None

        print(f"\n{'='*60}")
        print(f"SMART CONTENT PIPELINE: {topic}")
        print(f"{'='*60}")

        # Stage 1: Research
        print(f"\n[STAGE] Stage 1: Research")
        for attempt in range(1, max_stage_retries + 1):
            research_result = self._research_stage(topic)
            result['total_cost'] += 0.01
            result['stage_attempts']['research'] = attempt

            result['stage_history'].append({
                'stage': 'research',
                'attempt': attempt,
                'success': research_result.success,
                'errors': research_result.errors
            })

            status = '[PASS]' if research_result.success else f'[FAIL] {research_result.errors}'
            print(f"   Attempt {attempt}: {status}")

            if research_result.success:
                research = research_result.output
                break

        if not research:
            print("[FAIL] Research stage failed completely")
            result['time_seconds'] = time.time() - start_time
            return result

        # Stage 2: Outline
        print(f"\n[OUTLINE] Stage 2: Outline")
        for attempt in range(1, max_stage_retries + 1):
            outline_result = self._outline_stage(topic, research)
            result['total_cost'] += 0.01
            result['stage_attempts']['outline'] = attempt

            result['stage_history'].append({
                'stage': 'outline',
                'attempt': attempt,
                'success': outline_result.success,
                'errors': outline_result.errors
            })

            status = '[PASS]' if outline_result.success else f'[FAIL] {outline_result.errors}'
            print(f"   Attempt {attempt}: {status}")

            if outline_result.success:
                outline = outline_result.output
                break

        if not outline:
            print("[FAIL] Outline stage failed - research wasted")
            result['wasted_stages'] += 1
            result['time_seconds'] = time.time() - start_time
            return result

        # Stage 3: Draft
        print(f"\n[WRITE]  Stage 3: Draft")
        for attempt in range(1, max_stage_retries + 1):
            draft_result = self._draft_stage(topic, outline, target_length)
            result['total_cost'] += 0.02
            result['stage_attempts']['draft'] = attempt

            result['stage_history'].append({
                'stage': 'draft',
                'attempt': attempt,
                'success': draft_result.success,
                'errors': draft_result.errors
            })

            status = '[PASS]' if draft_result.success else f'[FAIL] {draft_result.errors}'
            print(f"   Attempt {attempt}: {status}")

            if draft_result.success:
                draft = draft_result.output
                break

        if not draft:
            print("[FAIL] Draft stage failed - research + outline wasted")
            result['wasted_stages'] += 2
            result['time_seconds'] = time.time() - start_time
            return result

        # Stage 4: Polish
        print(f"\n[POLISH] Stage 4: Polish")
        for attempt in range(1, max_stage_retries + 1):
            polish_result = self._polish_stage(draft)
            result['total_cost'] += 0.02
            result['stage_attempts']['polish'] = attempt

            result['stage_history'].append({
                'stage': 'polish',
                'attempt': attempt,
                'success': polish_result.success,
                'errors': polish_result.errors
            })

            status = '[PASS]' if polish_result.success else f'[FAIL] {polish_result.errors}'
            print(f"   Attempt {attempt}: {status}")

            if polish_result.success:
                final = polish_result.output
                break

        if not final:
            print("[FAIL] Polish stage failed - all stages wasted")
            result['wasted_stages'] += 3
            result['time_seconds'] = time.time() - start_time
            return result

        # SUCCESS
        result['success'] = True
        result['final_content'] = final
        result['word_count'] = len(final.split())
        result['time_seconds'] = time.time() - start_time

        print(f"\n[PASS] Pipeline complete!")
        print(f"   Words: {result['word_count']}")
        print(f"   Cost: ${result['total_cost']:.3f}")
        print(f"   Time: {result['time_seconds']:.1f}s")
        print(f"   Wasted stages: {result['wasted_stages']}")

        return result

    def _call_gpt4o(
        self,
        system_msg: str,
        prompt: str,
        temperature: float = 0.3,
        max_tokens: int = 2000
    ) -> str:
        """Call GPT-4o API."""
        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": "gpt-4o",
            "messages": [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": prompt}
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

        return result["choices"][0]["message"]["content"]


def run_experiment(num_trials: int = 5):
    """Run smart control content experiment."""
    # Load .env from experiments root
    env_path = Path(__file__).parent.parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("[ERROR] OPENAI_API_KEY not set")
        print("Run: python ../../setup_api_key.py")
        sys.exit(1)

    # Load dataset
    dataset_path = Path(__file__).parent.parent.parent / "datasets" / "content_topics.json"
    with open(dataset_path) as f:
        topics = json.load(f)

    print(f"\n{'='*60}")
    print("SMART CONTROL EXPERIMENT: Content Generation")
    print(f"{'='*60}")
    print(f"Trials: {num_trials}")
    print()

    pipeline = SmartContentPipeline(api_key)
    results = []

    for i in range(num_trials):
        topic_data = topics[i % len(topics)]

        print(f"\n{'====='*60}")
        print(f"TRIAL {i+1}/{num_trials}")
        print(f"Topic: {topic_data['topic']}")
        print(f"Complexity: {topic_data['complexity']}")
        print(f"{'====='*60}")

        result = pipeline.generate(
            topic=topic_data['topic'],
            target_length=1800,
            max_stage_retries=2
        )

        # Add metadata
        result['trial_id'] = i + 1
        result['topic'] = topic_data['topic']
        result['complexity'] = topic_data['complexity']
        result['method'] = 'smart_control'
        result['timestamp'] = datetime.utcnow().isoformat()

        results.append(result)

        # Progress
        successes = sum(1 for r in results if r['success'])
        success_rate = successes / len(results) * 100
        avg_cost = sum(r['total_cost'] for r in results) / len(results)
        avg_wasted = sum(r['wasted_stages'] for r in results) / len(results)

        print(f"\n[PROGRESS] Progress:")
        print(f"   Success: {successes}/{len(results)} ({success_rate:.1f}%)")
        print(f"   Avg cost: ${avg_cost:.3f}")
        print(f"   Avg wasted stages: {avg_wasted:.2f}")

        # Rate limit: GPT-4o Tier 3 is generous (10,000 RPM) but 4-stage
        # pipelines can burst. 3s between trials is enough to avoid hitting
        # token-per-minute limits on consecutive long drafts.
        if i < num_trials - 1:
            time.sleep(3)

    # Save results
    output_path = Path(__file__).parent.parent / "results" / f"smart_control_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Create aggregate (without content to save space)
    json_results = [
        {k: v for k, v in r.items() if k != 'final_content'}
        for r in results
    ]

    with open(output_path, 'w') as f:
        json.dump({
            "experiment": "exp4_content_smart_control",
            "trials": num_trials,
            "results": json_results,
            "summary": {
                "total_trials": num_trials,
                "successful": sum(1 for r in results if r['success']),
                "success_rate": sum(1 for r in results if r['success']) / num_trials,
                "avg_attempts_total": sum(sum(r['stage_attempts'].values()) for r in results) / num_trials,
                "avg_cost": sum(r['total_cost'] for r in results) / num_trials,
                "avg_wasted_stages": sum(r['wasted_stages'] for r in results) / num_trials,
                "avg_word_count": sum(r['word_count'] for r in results if r['success']) / max(sum(1 for r in results if r['success']), 1)
            }
        }, f, indent=2)

    print(f"\n[PASS] Results saved to: {output_path}")

    # Print summary
    summary = json.load(open(output_path))["summary"]
    print(f"\n{'='*60}")
    print("SMART CONTROL SUMMARY (Content Pipeline)")
    print(f"{'='*60}")
    print(f"Total Trials:        {summary['total_trials']}")
    print(f"Successful:          {summary['successful']} ({summary['success_rate']:.1%})")
    print(f"Avg Total Attempts:  {summary['avg_attempts_total']:.2f}")
    print(f"Avg Cost:            ${summary['avg_cost']:.3f}")
    print(f"Avg Wasted Stages:   {summary['avg_wasted_stages']:.2f}")
    print(f"Avg Word Count:      {summary['avg_word_count']:.0f}")
    print(f"{'='*60}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Exp4 Smart Control: Engineered Content Pipeline")
    parser.add_argument("--trials", type=int, default=5, help="Number of trials")
    args = parser.parse_args()

    run_experiment(num_trials=args.trials)
