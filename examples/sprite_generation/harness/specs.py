"""
Sprite-specific specifications for Manifold orchestration.

These specs validate sprite generation quality at each stage:
- Image dimensions (1024x1024 minimum for GPT models)
- Extraction quality (grid layout preserved)
- Progress validation (situation changed between retries)
"""

from manifold import Spec, SpecResult, Context
from typing import Any


class ImageDimensionsSpec(Spec):
    """
    Validates that generated image meets minimum dimensions.

    GPT image models always output 1024x1024, but this spec
    ensures we never accidentally accept smaller images.
    """

    def __init__(self, min_width: int = 1024, min_height: int = 1024):
        self._min_width = min_width
        self._min_height = min_height

    @property
    def rule_id(self) -> str:
        return "image_dimensions_valid"

    @property
    def tags(self) -> tuple[str, ...]:
        return ("postcondition", "image", "quality")

    def evaluate(self, context: Context, candidate: Any = None) -> SpecResult:
        """
        Validate image dimensions from candidate output.

        Args:
            context: Current workflow context
            candidate: Dict with 'width' and 'height' keys

        Returns:
            SpecResult indicating pass/fail
        """
        if candidate is None or not isinstance(candidate, dict):
            return SpecResult.fail(
                self.rule_id,
                "No image metadata to validate",
                suggested_fix="Ensure agent returns dict with 'width' and 'height'",
                tags=self.tags,
            )

        width = candidate.get("width", 0)
        height = candidate.get("height", 0)

        if width >= self._min_width and height >= self._min_height:
            return SpecResult.ok(
                self.rule_id,
                f"Image dimensions OK: {width}x{height}",
                tags=self.tags,
                data={"width": width, "height": height},
            )

        return SpecResult.fail(
            self.rule_id,
            f"Image too small: {width}x{height} (need {self._min_width}x{self._min_height})",
            suggested_fix=f"Request image size >= {self._min_width}x{self._min_height}",
            tags=self.tags,
            data={
                "actual_width": width,
                "actual_height": height,
                "min_width": self._min_width,
                "min_height": self._min_height,
            },
        )


class SpriteExtractionSpec(Spec):
    """
    Validates that sprite extraction from grid succeeded.

    This checks that the expected number of sprite frames
    were successfully extracted from the generated grid.
    """

    @property
    def rule_id(self) -> str:
        return "sprite_extraction_succeeded"

    @property
    def tags(self) -> tuple[str, ...]:
        return ("postcondition", "extraction", "quality")

    def evaluate(self, context: Context, candidate: Any = None) -> SpecResult:
        """
        Validate extraction succeeded.

        Checks context.data for:
        - expected_frames: How many frames should be extracted
        - extracted_frames: How many were actually extracted

        Args:
            context: Current workflow context
            candidate: Agent output (not used, we check context)

        Returns:
            SpecResult indicating extraction success
        """
        expected = context.get_data("expected_frames", 0)
        extracted = context.get_data("extracted_frames", 0)

        if expected == 0:
            return SpecResult.fail(
                self.rule_id,
                "No expected_frames defined in context",
                suggested_fix="Set context.data['expected_frames'] before extraction",
                tags=self.tags,
            )

        if extracted >= expected:
            return SpecResult.ok(
                self.rule_id,
                f"Extraction succeeded: {extracted}/{expected} frames",
                tags=self.tags,
                data={"expected": expected, "extracted": extracted},
            )

        return SpecResult.fail(
            self.rule_id,
            f"Extraction incomplete: {extracted}/{expected} frames",
            suggested_fix="Regenerate with clearer grid constraints or adjust extraction logic",
            tags=self.tags,
            data={"expected": expected, "extracted": extracted, "missing": expected - extracted},
        )


class GridLayoutValidSpec(Spec):
    """
    Validates that GPT respected the NxN grid layout.

    This ensures the prompt instructions were followed
    and sprites are arranged in the expected grid.
    """

    @property
    def rule_id(self) -> str:
        return "grid_layout_valid"

    @property
    def tags(self) -> tuple[str, ...]:
        return ("postcondition", "layout", "quality")

    def evaluate(self, context: Context, candidate: Any = None) -> SpecResult:
        """
        Validate grid layout from context.

        Checks:
        - grid_size: Expected NxN grid
        - detected_grid: Actual grid detected in image

        Args:
            context: Current workflow context
            candidate: Not used

        Returns:
            SpecResult for grid layout validation
        """
        expected_grid = context.get_data("grid_size")
        detected_grid = context.get_data("detected_grid")

        if expected_grid is None:
            return SpecResult.fail(
                self.rule_id,
                "No expected grid_size in context",
                suggested_fix="Set context.data['grid_size'] = N for NxN grid",
                tags=self.tags,
            )

        if detected_grid is None:
            return SpecResult.fail(
                self.rule_id,
                "Grid detection not performed",
                suggested_fix="Run grid detection on generated image",
                tags=self.tags,
            )

        if detected_grid == expected_grid:
            return SpecResult.ok(
                self.rule_id,
                f"Grid layout correct: {detected_grid}x{detected_grid}",
                tags=self.tags,
                data={"grid_size": detected_grid},
            )

        return SpecResult.fail(
            self.rule_id,
            f"Grid mismatch: expected {expected_grid}x{expected_grid}, got {detected_grid}x{detected_grid}",
            suggested_fix="Strengthen grid constraints in prompt or regenerate",
            tags=self.tags,
            data={"expected": expected_grid, "detected": detected_grid},
        )


class HasGlobalStyleSpec(Spec):
    """Pre-condition: global_style must be defined."""

    @property
    def rule_id(self) -> str:
        return "has_global_style"

    @property
    def tags(self) -> tuple[str, ...]:
        return ("precondition", "config")

    def evaluate(self, context: Context, candidate: Any = None) -> SpecResult:
        style = context.get_data("global_style")

        if style and len(str(style).strip()) > 0:
            return SpecResult.ok(self.rule_id, f"Style defined: {style}", tags=self.tags)

        return SpecResult.fail(
            self.rule_id,
            "Missing global_style",
            suggested_fix="Set context.data['global_style'] = 'Pixel Art' (or other style)",
            tags=self.tags,
        )


class PromptNotEmptySpec(Spec):
    """Post-condition: Generated prompt must not be empty."""

    @property
    def rule_id(self) -> str:
        return "prompt_not_empty"

    @property
    def tags(self) -> tuple[str, ...]:
        return ("postcondition", "prompt")

    def evaluate(self, context: Context, candidate: Any = None) -> SpecResult:
        if candidate and len(str(candidate).strip()) > 0:
            length = len(str(candidate))
            return SpecResult.ok(
                self.rule_id,
                f"Prompt generated: {length} chars",
                tags=self.tags,
                data={"prompt_length": length},
            )

        return SpecResult.fail(
            self.rule_id,
            "Generated prompt is empty",
            suggested_fix="Check prompt generation logic",
            tags=self.tags,
        )
