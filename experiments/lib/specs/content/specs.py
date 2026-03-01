"""
Specs for multi-step content generation validation.
"""

from manifold import Spec, SpecResult, Context
from typing import Any
import re


class HasMinItemsSpec(Spec):
    """
    Validates that a list field has minimum number of items.

    Used for research sources, outline sections, etc.
    """

    def __init__(self, field: str, min_count: int):
        """
        Args:
            field: Name of list field in context or candidate
            min_count: Minimum required items
        """
        self._field = field
        self._min_count = min_count

    @property
    def rule_id(self) -> str:
        return f"has_min_items:{self._field}"

    @property
    def tags(self) -> tuple[str, ...]:
        return ("postcondition", "count", "research")

    def evaluate(self, context: Context, candidate: Any = None) -> SpecResult:
        """Check that field has minimum items."""
        # Try candidate first, then context
        items = None

        if isinstance(candidate, dict) and self._field in candidate:
            items = candidate[self._field]
        elif context.has_data(self._field):
            items = context.get_data(self._field)

        if items is None:
            return SpecResult.fail(
                self.rule_id,
                f"Field '{self._field}' not found",
                suggested_fix=f"Ensure step produces '{self._field}'",
                tags=self.tags
            )

        if not isinstance(items, (list, tuple)):
            return SpecResult.fail(
                self.rule_id,
                f"Field '{self._field}' is not a list (got {type(items).__name__})",
                suggested_fix=f"Ensure '{self._field}' is a list",
                tags=self.tags
            )

        count = len(items)

        if count >= self._min_count:
            return SpecResult.ok(
                self.rule_id,
                f"{self._field} has {count} items (need {self._min_count})",
                tags=self.tags,
                data={"count": count, "min_count": self._min_count}
            )

        return SpecResult.fail(
            self.rule_id,
            f"{self._field} has only {count} items (need {self._min_count})",
            suggested_fix=f"Generate at least {self._min_count} {self._field}",
            tags=self.tags,
            data={"count": count, "min_count": self._min_count, "missing": self._min_count - count}
        )


class OutlineValidationSpec(Spec):
    """
    Validates outline structure (intro, sections, conclusion).
    """

    def __init__(
        self,
        min_sections: int = 3,
        has_intro: bool = True,
        has_conclusion: bool = True
    ):
        """
        Args:
            min_sections: Minimum number of main sections
            has_intro: Whether intro is required
            has_conclusion: Whether conclusion is required
        """
        self._min_sections = min_sections
        self._has_intro = has_intro
        self._has_conclusion = has_conclusion

    @property
    def rule_id(self) -> str:
        return "outline_structure_valid"

    @property
    def tags(self) -> tuple[str, ...]:
        return ("postcondition", "structure", "outline")

    def evaluate(self, context: Context, candidate: Any = None) -> SpecResult:
        """
        Validate outline structure.

        Expected candidate format (as string):
        # Introduction
        ...
        # Section 1
        ...
        # Section 2
        ...
        # Conclusion
        ...
        """
        outline = candidate if isinstance(candidate, str) else str(candidate)

        if not outline or len(outline.strip()) == 0:
            return SpecResult.fail(
                self.rule_id,
                "Outline is empty",
                suggested_fix="Generate outline with intro, sections, conclusion",
                tags=self.tags
            )

        # Count markdown headings (# Header)
        headings = re.findall(r'^#+\s+(.+)$', outline, re.MULTILINE)

        if not headings:
            return SpecResult.fail(
                self.rule_id,
                "No headings found in outline",
                suggested_fix="Use markdown headings (# Section Name)",
                tags=self.tags
            )

        # Check for intro
        has_intro_heading = any(
            'intro' in h.lower() or 'overview' in h.lower()
            for h in headings
        )

        if self._has_intro and not has_intro_heading:
            return SpecResult.fail(
                self.rule_id,
                "Missing introduction section",
                suggested_fix="Add introduction section to outline",
                tags=self.tags,
                data={"headings": headings}
            )

        # Check for conclusion
        has_conclusion_heading = any(
            'conclusion' in h.lower() or 'summary' in h.lower()
            for h in headings
        )

        if self._has_conclusion and not has_conclusion_heading:
            return SpecResult.fail(
                self.rule_id,
                "Missing conclusion section",
                suggested_fix="Add conclusion section to outline",
                tags=self.tags,
                data={"headings": headings}
            )

        # Count main sections (exclude intro/conclusion)
        main_sections = [
            h for h in headings
            if 'intro' not in h.lower()
            and 'conclusion' not in h.lower()
            and 'overview' not in h.lower()
            and 'summary' not in h.lower()
        ]

        section_count = len(main_sections)

        if section_count >= self._min_sections:
            return SpecResult.ok(
                self.rule_id,
                f"Valid outline: {section_count} sections, intro={has_intro_heading}, conclusion={has_conclusion_heading}",
                tags=self.tags,
                data={
                    "section_count": section_count,
                    "has_intro": has_intro_heading,
                    "has_conclusion": has_conclusion_heading,
                    "headings": headings
                }
            )

        return SpecResult.fail(
            self.rule_id,
            f"Only {section_count} sections (need {self._min_sections})",
            suggested_fix=f"Add {self._min_sections - section_count} more sections",
            tags=self.tags,
            data={
                "section_count": section_count,
                "min_sections": self._min_sections,
                "headings": headings
            }
        )


class OutlineComplianceSpec(Spec):
    """
    Validates that draft content follows outline structure.

    Checks that draft has headings matching the outline.
    """

    def __init__(self, strict: bool = False):
        """
        Args:
            strict: If True, headings must match exactly. If False, allows variations.
        """
        self._strict = strict

    @property
    def rule_id(self) -> str:
        return "follows_outline"

    @property
    def tags(self) -> tuple[str, ...]:
        return ("postcondition", "compliance", "structure")

    def evaluate(self, context: Context, candidate: Any = None) -> SpecResult:
        """
        Check that draft content follows outline.

        Looks for 'outline' in context.data, compares headings with draft.
        """
        outline = context.get_data("outline")

        if not outline:
            return SpecResult.fail(
                self.rule_id,
                "No outline in context to compare against",
                suggested_fix="Ensure outline step runs before draft",
                tags=self.tags
            )

        draft = candidate if isinstance(candidate, str) else str(candidate)

        if not draft or len(draft.strip()) == 0:
            return SpecResult.fail(
                self.rule_id,
                "Draft is empty",
                suggested_fix="Generate draft content",
                tags=self.tags
            )

        # Extract headings from both
        outline_headings = re.findall(r'^#+\s+(.+)$', str(outline), re.MULTILINE)
        draft_headings = re.findall(r'^#+\s+(.+)$', draft, re.MULTILINE)

        if not draft_headings:
            return SpecResult.fail(
                self.rule_id,
                "Draft has no headings",
                suggested_fix="Include section headings from outline",
                tags=self.tags
            )

        # Check compliance
        if self._strict:
            # Exact match required
            if outline_headings == draft_headings:
                return SpecResult.ok(
                    self.rule_id,
                    f"Draft follows outline exactly ({len(draft_headings)} sections)",
                    tags=self.tags,
                    data={"headings": draft_headings}
                )
            else:
                return SpecResult.fail(
                    self.rule_id,
                    "Draft headings don't match outline",
                    suggested_fix="Follow outline structure exactly",
                    tags=self.tags,
                    data={
                        "outline_headings": outline_headings,
                        "draft_headings": draft_headings
                    }
                )
        else:
            # Fuzzy match - check if most outline headings are in draft
            outline_lower = [h.lower().strip() for h in outline_headings]
            draft_lower = [h.lower().strip() for h in draft_headings]

            matched = sum(
                1 for oh in outline_lower
                if any(oh in dh or dh in oh for dh in draft_lower)
            )

            match_ratio = matched / len(outline_headings) if outline_headings else 0

            if match_ratio >= 0.7:  # 70% match is good enough
                return SpecResult.ok(
                    self.rule_id,
                    f"Draft follows outline ({matched}/{len(outline_headings)} sections match)",
                    tags=self.tags,
                    data={
                        "matched": matched,
                        "total": len(outline_headings),
                        "match_ratio": match_ratio
                    }
                )

            return SpecResult.fail(
                self.rule_id,
                f"Draft only matches {matched}/{len(outline_headings)} outline sections",
                suggested_fix="Follow outline structure more closely",
                tags=self.tags,
                data={
                    "matched": matched,
                    "total": len(outline_headings),
                    "match_ratio": match_ratio,
                    "outline_headings": outline_headings,
                    "draft_headings": draft_headings
                }
            )


class LengthRangeSpec(Spec):
    """
    Validates that content length (word count) is within range.
    """

    def __init__(self, min_words: int, max_words: int):
        """
        Args:
            min_words: Minimum word count
            max_words: Maximum word count
        """
        self._min_words = min_words
        self._max_words = max_words

    @property
    def rule_id(self) -> str:
        return "length_in_range"

    @property
    def tags(self) -> tuple[str, ...]:
        return ("postcondition", "length", "quality")

    def evaluate(self, context: Context, candidate: Any = None) -> SpecResult:
        """Check word count of content."""
        content = candidate if isinstance(candidate, str) else str(candidate)

        # Simple word count (split on whitespace)
        words = content.split()
        word_count = len(words)

        if self._min_words <= word_count <= self._max_words:
            return SpecResult.ok(
                self.rule_id,
                f"Length OK: {word_count} words (target: {self._min_words}-{self._max_words})",
                tags=self.tags,
                data={"word_count": word_count, "min": self._min_words, "max": self._max_words}
            )

        if word_count < self._min_words:
            return SpecResult.fail(
                self.rule_id,
                f"Content too short: {word_count} words (need {self._min_words})",
                suggested_fix=f"Expand content to at least {self._min_words} words",
                tags=self.tags,
                data={
                    "word_count": word_count,
                    "min": self._min_words,
                    "missing": self._min_words - word_count
                }
            )

        return SpecResult.fail(
            self.rule_id,
            f"Content too long: {word_count} words (max {self._max_words})",
            suggested_fix=f"Reduce content to max {self._max_words} words",
            tags=self.tags,
            data={
                "word_count": word_count,
                "max": self._max_words,
                "excess": word_count - self._max_words
            }
        )


class GrammarCheckSpec(Spec):
    """
    Basic grammar validation (detects obvious errors).

    Note: This is a simplified check. For production, use a real
    grammar checker like LanguageTool.
    """

    # Common grammar error patterns
    PATTERNS = [
        (r'\bi\s+[a-z]', "Lowercase after 'I'"),  # "i am" should be "I am"
        (r'\.\s+[a-z]', "Lowercase after period"),
        (r'\s{2,}', "Multiple spaces"),
        (r'[.!?]{2,}', "Repeated punctuation"),
    ]

    @property
    def rule_id(self) -> str:
        return "no_grammar_errors"

    @property
    def tags(self) -> tuple[str, ...]:
        return ("postcondition", "quality", "grammar")

    def evaluate(self, context: Context, candidate: Any = None) -> SpecResult:
        """Check for obvious grammar errors."""
        content = candidate if isinstance(candidate, str) else str(candidate)

        if not content or len(content.strip()) == 0:
            return SpecResult.fail(
                self.rule_id,
                "Content is empty",
                suggested_fix="Generate content",
                tags=self.tags
            )

        errors = []

        for pattern, description in self.PATTERNS:
            matches = re.finditer(pattern, content)
            for match in matches:
                errors.append({
                    "type": description,
                    "position": match.start(),
                    "text": match.group()[:20]  # First 20 chars
                })

        # Limit to first 10 errors (don't overwhelm)
        errors = errors[:10]

        if not errors:
            return SpecResult.ok(
                self.rule_id,
                "No obvious grammar errors detected",
                tags=self.tags
            )

        return SpecResult.fail(
            self.rule_id,
            f"Found {len(errors)} potential grammar errors",
            suggested_fix="Review and fix grammar issues",
            tags=self.tags,
            data={"errors": errors, "error_count": len(errors)}
        )
