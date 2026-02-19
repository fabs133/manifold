"""
Experiment 1 Smart Control: Engineered DALL-E 3 Sprite Generation

This represents what a COMPETENT engineer would build (not a framework):
- Sophisticated prompting (system message + structured constraints)
- Thorough validation (multiple checks)
- Adaptive retry (adjusts prompt based on failures)
- Detailed logging and tracking

This is the REAL comparison point for Manifold.
"""

import os
import sys
import json
import time
import urllib.request
from pathlib import Path
from typing import Dict, List, Tuple
from datetime import datetime

# Add shared utilities
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from shared.validation_utils import ImageValidator

# For image handling
try:
    from PIL import Image
    from io import BytesIO
except ImportError:
    print("[ERROR] PIL not installed. Run: pip install Pillow")
    sys.exit(1)


class SmartSpriteGenerator:
    """
    Smart baseline: well-engineered sprite generation.

    Key features (that naive control lacks):
    - System message for model steering
    - Structured prompt with CRITICAL emphasis
    - Multi-check validation
    - Adaptive retry (changes prompt based on failures)
    - Loop detection (doesn't retry identical prompts)
    - Detailed result tracking
    """

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.validator = ImageValidator()

    def _build_system_message(self) -> str:
        """Engineered system message for better model behavior."""
        return """You are an expert pixel art sprite sheet generator.

Your core competencies:
- Precise grid layouts with exact spacing
- Consistent pixel art style across all sprites
- Clean separation between sprites
- Proper canvas dimensions (1024x1024)

Always prioritize:
1. Grid alignment and spacing (CRITICAL)
2. Style consistency
3. Clear visual separation between sprites
4. Proper canvas usage"""

    def _build_initial_prompt(self, description: str, frames: int, style: str, grid_size: int) -> str:
        """Carefully crafted initial prompt with structure."""
        return f"""Create a sprite sheet with these STRICT requirements:

LAYOUT (CRITICAL - MUST FOLLOW):
- Exactly {grid_size}x{grid_size} grid ({frames} total sprites)
- Each sprite 256x256 pixels
- 16-pixel margins between sprites minimum
- Perfect alignment (no drift or skew)
- Use full 1024x1024 canvas

CONTENT:
- {description}
- {style} style
- Consistent art style across ALL sprites
- Varied but coherent designs

TECHNICAL:
- Pure white background (#FFFFFF)
- Sprites centered in their grid cells
- Clean edges
- No sprites touching each other

 CRITICAL: Grid precision is MANDATORY. Every sprite must be in its designated cell with proper spacing."""

    def _adapt_prompt(
        self,
        base_description: str,
        base_frames: int,
        base_style: str,
        base_grid_size: int,
        validation_failures: List[str],
        attempt: int
    ) -> str:
        """
        Adapt prompt based on validation failures.

        This is the key smart control feature: instead of blind retry,
        we analyze what failed and emphasize those aspects.
        """
        # Start with base prompt
        adapted = self._build_initial_prompt(base_description, base_frames, base_style, base_grid_size)

        # Add specific emphasis based on failures
        emphasis = []

        if "dimensions" in str(validation_failures):
            emphasis.append("\n\n CRITICAL EMPHASIS: Use FULL 1024x1024 canvas.")
            emphasis.append("DO NOT generate smaller images. Canvas MUST be 1024x1024 pixels.")

        if "grid" in str(validation_failures):
            emphasis.append("\n\n CRITICAL EMPHASIS: STRICT grid layout required.")
            emphasis.append(f"Sprites MUST be arranged in perfect {base_grid_size}x{base_grid_size} grid.")
            emphasis.append("Each sprite in its designated cell. NO exceptions.")

        if "separation" in str(validation_failures):
            emphasis.append("\n\n CRITICAL EMPHASIS: Clear spacing between sprites.")
            emphasis.append("Minimum 16-pixel gaps. Sprites MUST NOT touch.")
            emphasis.append("Use pure white (#FFFFFF) background for separation.")

        if emphasis:
            adapted += "\n" + "".join(emphasis)

        return adapted

    def _validate_thoroughly(
        self,
        image: Image.Image,
        expected_grid_size: int
    ) -> Tuple[bool, List[str]]:
        """
        Sophisticated multi-check validation.

        Returns: (success, list_of_failure_reasons)
        """
        failures = []

        # Check 1: Dimensions
        valid, msg = self.validator.validate_dimensions(image, 1024, 1024)
        if not valid:
            failures.append(f"dimensions:{msg}")

        # Check 2: Grid detection
        expected_cells = expected_grid_size * expected_grid_size
        valid, msg = self.validator.detect_grid(image, expected_cells)
        if not valid:
            failures.append(f"grid:{msg}")

        # Check 3: Sprite count
        count, msg = self.validator.count_sprites(image, expected_grid_size)
        if count != expected_cells:
            failures.append(f"sprite_count:{count}_expected_{expected_cells}")

        # Check 4: Separation
        valid, msg = self.validator.check_separation(image, min_gap=8)
        if not valid:
            failures.append(f"separation:{msg}")

        success = len(failures) == 0

        return success, failures

    def generate(
        self,
        description: str,
        frames: int,
        style: str,
        grid_size: int,
        max_attempts: int = 3
    ) -> Dict:
        """
        Generate sprite with smart retry.

        Returns detailed metrics for benchmarking.
        """
        start_time = time.time()

        result = {
            "success": False,
            "attempts": 0,
            "total_cost": 0.0,
            "time_seconds": 0.0,
            "validation_history": [],
            "adaptations": [],
            "loop_detected": False,
            "duplicate_failures": 0,
        }

        # Track prompts for loop detection
        seen_prompts = set()
        last_failures = None

        system_msg = self._build_system_message()

        for attempt in range(1, max_attempts + 1):
            result["attempts"] = attempt

            # Build prompt (adaptive on retry)
            if attempt == 1:
                prompt = self._build_initial_prompt(description, frames, style, grid_size)
            else:
                prompt = self._adapt_prompt(
                    description, frames, style, grid_size,
                    last_failures, attempt
                )
                result["adaptations"].append({
                    "attempt": attempt,
                    "failures": last_failures
                })

            # Loop detection
            prompt_hash = hash(prompt)
            if prompt_hash in seen_prompts:
                result["loop_detected"] = True
                break
            seen_prompts.add(prompt_hash)

            print(f"   Attempt {attempt}/{max_attempts}")
            print(f"   Prompt: {len(prompt)} chars")
            if attempt > 1:
                print(f"   Adapted for: {last_failures[:2]}")  # Show first 2 failures

            try:
                # Call DALL-E 3
                image_url = self._call_dalle3(system_msg, prompt)
                result["total_cost"] += 0.04  # Standard quality

                # Download image
                image = self._download_image(image_url)

                # Validate
                success, failures = self._validate_thoroughly(image, grid_size)

                result["validation_history"].append({
                    "attempt": attempt,
                    "success": success,
                    "failures": failures
                })

                print(f"   Validation: {'[PASS] PASS' if success else f'[FAIL] FAIL'}")
                if failures:
                    print(f"   Failures: {failures[:3]}")  # Show first 3

                if success:
                    result["success"] = True
                    break
                else:
                    # Check for duplicate failures (blind retry indicator)
                    if last_failures and set(failures) == set(last_failures):
                        result["duplicate_failures"] += 1

                    last_failures = failures

            except Exception as e:
                print(f"   [FAIL] Error: {e}")
                result["validation_history"].append({
                    "attempt": attempt,
                    "error": str(e)
                })
                break

        result["time_seconds"] = time.time() - start_time
        return result

    def _call_dalle3(self, system_msg: str, prompt: str) -> str:
        """Call DALL-E 3 API (system message via prompt prefix)."""
        # DALL-E 3 doesn't support system messages directly,
        # so we prepend it to the prompt
        full_prompt = f"{system_msg}\n\n{prompt}"

        url = "https://api.openai.com/v1/images/generations"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": "dall-e-3",
            "prompt": full_prompt,
            "n": 1,
            "size": "1024x1024",
            "quality": "standard",
            "response_format": "url"
        }

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode('utf-8'),
            headers=headers,
            method='POST'
        )

        with urllib.request.urlopen(req, timeout=120) as response:
            result = json.loads(response.read().decode('utf-8'))

        return result["data"][0]["url"]

    def _download_image(self, url: str) -> Image.Image:
        """Download image from URL."""
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=30) as response:
            data = response.read()

        return Image.open(BytesIO(data))


def run_experiment(num_trials: int = 5):
    """Run smart control experiment."""
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
    dataset_path = Path(__file__).parent.parent.parent / "datasets" / "sprite_prompts.json"
    with open(dataset_path) as f:
        prompts = json.load(f)

    print(f"\n{'='*60}")
    print("SMART CONTROL EXPERIMENT: DALL-E 3 Sprites")
    print(f"{'='*60}")
    print(f"Trials: {num_trials}")
    print()

    generator = SmartSpriteGenerator(api_key)
    results = []

    for i in range(num_trials):
        prompt_data = prompts[i % len(prompts)]

        print(f"\n{'====='*60}")
        print(f"TRIAL {i+1}/{num_trials}: {prompt_data['description']}")
        print(f"{'====='*60}")

        grid_size = int(prompt_data['expected_grid'].split('x')[0])

        result = generator.generate(
            description=prompt_data['description'],
            frames=prompt_data['frames'],
            style=prompt_data['style'],
            grid_size=grid_size,
            max_attempts=3
        )

        # Add metadata
        result["trial_id"] = i + 1
        result["method"] = "smart_control"
        result["model"] = "dall-e-3"
        result["description"] = prompt_data['description']
        result["timestamp"] = datetime.utcnow().isoformat()

        results.append(result)

        # Progress summary
        successes = sum(1 for r in results if r["success"])
        success_rate = successes / len(results) * 100
        avg_cost = sum(r["total_cost"] for r in results) / len(results)
        loops = sum(1 for r in results if r.get("loop_detected"))

        print(f"\n[PROGRESS] Progress:")
        print(f"   Success: {successes}/{len(results)} ({success_rate:.1f}%)")
        print(f"   Avg cost: ${avg_cost:.4f}")
        print(f"   Loops: {loops}")

    # Save results
    output_path = Path(__file__).parent.parent / "results" / f"smart_control_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w') as f:
        json.dump({
            "experiment": "exp1_dalle3_smart_control",
            "trials": num_trials,
            "results": results,
            "summary": {
                "total_trials": num_trials,
                "successful": sum(1 for r in results if r["success"]),
                "success_rate": sum(1 for r in results if r["success"]) / num_trials,
                "avg_attempts": sum(r["attempts"] for r in results) / num_trials,
                "avg_cost": sum(r["total_cost"] for r in results) / num_trials,
                "loop_incidents": sum(1 for r in results if r.get("loop_detected")),
                "duplicate_failure_incidents": sum(1 for r in results if r.get("duplicate_failures", 0) > 0)
            }
        }, f, indent=2)

    print(f"\n[PASS] Results saved to: {output_path}")

    # Print final summary
    summary = json.load(open(output_path))["summary"]
    print(f"\n{'='*60}")
    print("SMART CONTROL SUMMARY (DALL-E 3)")
    print(f"{'='*60}")
    print(f"Total Trials:         {summary['total_trials']}")
    print(f"Successful:           {summary['successful']} ({summary['success_rate']:.1%})")
    print(f"Avg Attempts:         {summary['avg_attempts']:.2f}")
    print(f"Avg Cost:             ${summary['avg_cost']:.4f}")
    print(f"Loop Incidents:       {summary['loop_incidents']}")
    print(f"Duplicate Failures:   {summary['duplicate_failure_incidents']}")
    print(f"{'='*60}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Exp1 Smart Control: Engineered DALL-E 3")
    parser.add_argument("--trials", type=int, default=5, help="Number of trials")
    args = parser.parse_args()

    run_experiment(num_trials=args.trials)
