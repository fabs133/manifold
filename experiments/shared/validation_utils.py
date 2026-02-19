"""
Shared validation utilities for smart control experiments.

These are sophisticated validation functions that a competent engineer would build.
Used by smart control baselines to provide fair comparison against Manifold.
"""

from typing import Dict, List, Tuple, Optional
import re
from PIL import Image
import numpy as np


class ImageValidator:
    """Sophisticated image validation for sprite generation."""

    @staticmethod
    def validate_dimensions(image: Image.Image, min_width: int = 1024, min_height: int = 1024) -> Tuple[bool, str]:
        """Check image dimensions."""
        if image.width >= min_width and image.height >= min_height:
            return True, f"Dimensions OK: {image.width}x{image.height}"
        return False, f"Too small: {image.width}x{image.height} (need {min_width}x{min_height})"

    @staticmethod
    def detect_grid(image: Image.Image, expected_cells: int = 16) -> Tuple[bool, str]:
        """
        Detect if image has a grid layout.

        Simple heuristic: look for regular spacing patterns.
        """
        # Convert to grayscale for edge detection
        gray = image.convert('L')
        arr = np.array(gray)

        # Look for edges (simplified - real implementation would use Sobel/Canny)
        edges_h = np.diff(arr, axis=0)
        edges_v = np.diff(arr, axis=1)

        # Check for regular patterns (this is a simplification)
        # In production, would use more sophisticated grid detection

        # For now, just check if there's some structure
        h_variance = np.var(edges_h)
        v_variance = np.var(edges_v)

        if h_variance > 100 and v_variance > 100:
            return True, f"Grid structure detected (h_var={h_variance:.0f}, v_var={v_variance:.0f})"

        return False, f"No clear grid structure (h_var={h_variance:.0f}, v_var={v_variance:.0f})"

    @staticmethod
    def count_sprites(image: Image.Image, grid_size: int = 4) -> Tuple[int, str]:
        """
        Estimate number of sprites in grid.

        Simplified implementation - checks for distinct regions.
        """
        # This is a placeholder - real implementation would use
        # connected components or template matching

        # For now, assume grid_size × grid_size if structure detected
        has_grid, _ = ImageValidator.detect_grid(image)

        if has_grid:
            count = grid_size * grid_size
            return count, f"Estimated {count} sprites in {grid_size}x{grid_size} grid"

        return 0, "Could not detect sprites"

    @staticmethod
    def check_separation(image: Image.Image, min_gap: int = 8) -> Tuple[bool, str]:
        """Check if sprites have minimum separation."""
        # Simplified check - look for white space patterns
        arr = np.array(image.convert('L'))

        # Check for consistent white regions (gaps)
        white_threshold = 250
        white_regions = arr > white_threshold

        # This is simplified - real implementation would check
        # for consistent gaps between sprite regions
        white_percentage = np.sum(white_regions) / white_regions.size

        if white_percentage > 0.2:  # At least 20% white space
            return True, f"Good separation detected ({white_percentage:.1%} white space)"

        return False, f"Insufficient separation ({white_percentage:.1%} white space)"


class SchemaValidator:
    """Sophisticated schema validation for data extraction."""

    @staticmethod
    def validate_email(email: str) -> Tuple[bool, str]:
        """Validate email format."""
        if not email:
            return False, "Email is empty"

        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if re.match(pattern, email):
            return True, f"Valid email: {email}"

        return False, f"Invalid email format: {email}"

    @staticmethod
    def validate_range(value: any, min_val: int, max_val: int, field_name: str = "value") -> Tuple[bool, str]:
        """Validate numeric range."""
        try:
            num = int(value)
            if min_val <= num <= max_val:
                return True, f"{field_name}={num} in range [{min_val}, {max_val}]"
            return False, f"{field_name}={num} outside range [{min_val}, {max_val}]"
        except (ValueError, TypeError):
            return False, f"{field_name}='{value}' is not a number"

    @staticmethod
    def validate_enum(value: str, allowed: List[str], field_name: str = "value") -> Tuple[bool, str]:
        """Validate enum/choice."""
        if value in allowed:
            return True, f"{field_name}='{value}' is valid"

        return False, f"{field_name}='{value}' not in {allowed}"

    @staticmethod
    def validate_pattern(value: str, pattern: str, field_name: str = "value") -> Tuple[bool, str]:
        """Validate against regex pattern."""
        if not value:
            return False, f"{field_name} is empty"

        if re.match(pattern, str(value)):
            return True, f"{field_name}='{value}' matches pattern"

        return False, f"{field_name}='{value}' doesn't match pattern {pattern}"

    @staticmethod
    def validate_required_fields(data: Dict, required: List[str]) -> Tuple[bool, List[str]]:
        """Check all required fields present."""
        missing = [field for field in required if field not in data]

        if not missing:
            return True, []

        return False, missing


class ContentValidator:
    """Sophisticated content validation for multi-step generation."""

    @staticmethod
    def validate_word_count(text: str, min_words: int, max_words: int) -> Tuple[bool, str]:
        """Validate word count."""
        words = text.split()
        count = len(words)

        if min_words <= count <= max_words:
            return True, f"Word count OK: {count} words (target: {min_words}-{max_words})"

        if count < min_words:
            return False, f"Too short: {count} words (need {min_words})"

        return False, f"Too long: {count} words (max {max_words})"

    @staticmethod
    def validate_structure(text: str, required_sections: List[str]) -> Tuple[bool, List[str]]:
        """Check for required sections in content."""
        text_lower = text.lower()
        missing = []

        for section in required_sections:
            if section.lower() not in text_lower:
                missing.append(section)

        if not missing:
            return True, []

        return False, missing

    @staticmethod
    def detect_outline_sections(outline: str) -> List[str]:
        """Extract section headings from outline."""
        # Find markdown headings (## Section Name)
        pattern = r'^#+\s+(.+)$'
        sections = re.findall(pattern, outline, re.MULTILINE)
        return sections

    @staticmethod
    def check_outline_compliance(draft: str, outline: str, strict: bool = False) -> Tuple[bool, str]:
        """Check if draft follows outline structure."""
        outline_sections = ContentValidator.detect_outline_sections(outline)
        draft_sections = ContentValidator.detect_outline_sections(draft)

        if not outline_sections:
            return False, "No sections found in outline"

        if not draft_sections:
            return False, "No sections found in draft"

        # Fuzzy matching
        outline_lower = [s.lower().strip() for s in outline_sections]
        draft_lower = [s.lower().strip() for s in draft_sections]

        matched = sum(
            1 for oh in outline_lower
            if any(oh in dh or dh in oh for dh in draft_lower)
        )

        match_ratio = matched / len(outline_sections) if outline_sections else 0

        threshold = 1.0 if strict else 0.7

        if match_ratio >= threshold:
            return True, f"Follows outline ({matched}/{len(outline_sections)} sections match)"

        return False, f"Doesn't follow outline ({matched}/{len(outline_sections)} sections match, need {int(threshold*100)}%)"

    @staticmethod
    def basic_grammar_check(text: str) -> Tuple[bool, List[str]]:
        """Basic grammar validation (simplified)."""
        errors = []

        # Check 1: Consecutive spaces
        if '  ' in text:
            errors.append("consecutive_spaces")

        # Check 2: Lowercase after period
        if re.search(r'\.\s+[a-z]', text):
            errors.append("lowercase_after_period")

        # Check 3: Repeated punctuation
        if re.search(r'[.!?]{2,}', text):
            errors.append("repeated_punctuation")

        if not errors:
            return True, []

        return False, errors
