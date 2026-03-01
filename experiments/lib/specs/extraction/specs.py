"""
Specs for structured data extraction validation.
"""

from manifold import Spec, SpecResult, Context
from typing import Any
import re


class HasRequiredFieldsSpec(Spec):
    """
    Validates that all required fields are present in extracted data.

    This is the most critical spec for data extraction - ensures
    all mandatory fields were successfully extracted.
    """

    def __init__(self, fields: list[str]):
        """
        Args:
            fields: List of required field names
        """
        self._fields = fields

    @property
    def rule_id(self) -> str:
        return "has_required_fields"

    @property
    def tags(self) -> tuple[str, ...]:
        return ("postcondition", "schema", "extraction")

    def evaluate(self, context: Context, candidate: Any = None) -> SpecResult:
        """
        Check that candidate dict has all required fields.

        Args:
            candidate: Dict with extracted data
        """
        if not isinstance(candidate, dict):
            return SpecResult.fail(
                self.rule_id,
                f"Candidate is not a dict (got {type(candidate).__name__})",
                suggested_fix="Ensure extraction returns a dictionary",
                tags=self.tags
            )

        missing = [f for f in self._fields if f not in candidate or candidate[f] is None]

        if not missing:
            return SpecResult.ok(
                self.rule_id,
                f"All {len(self._fields)} required fields present",
                tags=self.tags,
                data={"required_count": len(self._fields)}
            )

        return SpecResult.fail(
            self.rule_id,
            f"Missing required fields: {', '.join(missing)}",
            suggested_fix=f"Ensure extraction includes: {', '.join(missing)}",
            tags=self.tags,
            data={
                "missing_fields": missing,
                "required_fields": self._fields,
                "present_fields": list(candidate.keys())
            }
        )


class EmailValidationSpec(Spec):
    """
    Validates that a field contains a properly formatted email address.
    """

    # Simple email regex - not RFC 5322 compliant but good enough
    EMAIL_PATTERN = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')

    def __init__(self, field: str = "email"):
        """
        Args:
            field: Name of the field to validate
        """
        self._field = field

    @property
    def rule_id(self) -> str:
        return f"email_valid:{self._field}"

    @property
    def tags(self) -> tuple[str, ...]:
        return ("postcondition", "format", "extraction")

    def evaluate(self, context: Context, candidate: Any = None) -> SpecResult:
        """Validate email format in candidate dict."""
        if not isinstance(candidate, dict):
            return SpecResult.fail(
                self.rule_id,
                "Candidate is not a dict",
                suggested_fix="Ensure extraction returns dict",
                tags=self.tags
            )

        if self._field not in candidate:
            return SpecResult.fail(
                self.rule_id,
                f"Field '{self._field}' not found",
                suggested_fix=f"Ensure extraction includes '{self._field}'",
                tags=self.tags
            )

        email = candidate[self._field]

        if not isinstance(email, str):
            return SpecResult.fail(
                self.rule_id,
                f"Email field is not a string (got {type(email).__name__})",
                suggested_fix=f"Ensure '{self._field}' is extracted as string",
                tags=self.tags
            )

        if self.EMAIL_PATTERN.match(email):
            return SpecResult.ok(
                self.rule_id,
                f"Valid email: {email}",
                tags=self.tags,
                data={"email": email}
            )

        return SpecResult.fail(
            self.rule_id,
            f"Invalid email format: {email}",
            suggested_fix="Extract valid email address from input",
            tags=self.tags,
            data={"invalid_email": email}
        )


class RangeValidationSpec(Spec):
    """
    Validates that a numeric field falls within an expected range.
    """

    def __init__(self, field: str, min_val: int | float, max_val: int | float):
        """
        Args:
            field: Name of field to validate
            min_val: Minimum acceptable value (inclusive)
            max_val: Maximum acceptable value (inclusive)
        """
        self._field = field
        self._min = min_val
        self._max = max_val

    @property
    def rule_id(self) -> str:
        return f"range_valid:{self._field}"

    @property
    def tags(self) -> tuple[str, ...]:
        return ("postcondition", "range", "extraction")

    def evaluate(self, context: Context, candidate: Any = None) -> SpecResult:
        """Validate numeric range."""
        if not isinstance(candidate, dict):
            return SpecResult.fail(
                self.rule_id,
                "Candidate is not a dict",
                suggested_fix="Ensure extraction returns dict",
                tags=self.tags
            )

        if self._field not in candidate:
            return SpecResult.fail(
                self.rule_id,
                f"Field '{self._field}' not found",
                suggested_fix=f"Ensure extraction includes '{self._field}'",
                tags=self.tags
            )

        value = candidate[self._field]

        # Convert to number if string
        try:
            if isinstance(value, str):
                value = float(value) if '.' in value else int(value)
            elif not isinstance(value, (int, float)):
                raise ValueError(f"Cannot convert {type(value).__name__} to number")
        except (ValueError, TypeError) as e:
            return SpecResult.fail(
                self.rule_id,
                f"Field '{self._field}' is not numeric: {value}",
                suggested_fix=f"Extract '{self._field}' as number between {self._min} and {self._max}",
                tags=self.tags,
                data={"value": str(value), "error": str(e)}
            )

        if self._min <= value <= self._max:
            return SpecResult.ok(
                self.rule_id,
                f"{self._field}={value} within range [{self._min}, {self._max}]",
                tags=self.tags,
                data={"value": value, "min": self._min, "max": self._max}
            )

        return SpecResult.fail(
            self.rule_id,
            f"{self._field}={value} outside range [{self._min}, {self._max}]",
            suggested_fix=f"Extract valid {self._field} value between {self._min} and {self._max}",
            tags=self.tags,
            data={
                "value": value,
                "min": self._min,
                "max": self._max,
                "too_low": value < self._min,
                "too_high": value > self._max
            }
        )


class EnumValidationSpec(Spec):
    """
    Validates that a field contains one of the allowed values.
    """

    def __init__(self, field: str, allowed: list[str], case_sensitive: bool = True):
        """
        Args:
            field: Name of field to validate
            allowed: List of allowed values
            case_sensitive: Whether to do case-sensitive comparison
        """
        self._field = field
        self._allowed = allowed
        self._case_sensitive = case_sensitive

    @property
    def rule_id(self) -> str:
        return f"enum_valid:{self._field}"

    @property
    def tags(self) -> tuple[str, ...]:
        return ("postcondition", "enum", "extraction")

    def evaluate(self, context: Context, candidate: Any = None) -> SpecResult:
        """Validate enum value."""
        if not isinstance(candidate, dict):
            return SpecResult.fail(
                self.rule_id,
                "Candidate is not a dict",
                suggested_fix="Ensure extraction returns dict",
                tags=self.tags
            )

        if self._field not in candidate:
            return SpecResult.fail(
                self.rule_id,
                f"Field '{self._field}' not found",
                suggested_fix=f"Ensure extraction includes '{self._field}'",
                tags=self.tags
            )

        value = candidate[self._field]

        if not isinstance(value, str):
            value = str(value)

        # Check if value is in allowed list
        if self._case_sensitive:
            is_valid = value in self._allowed
        else:
            is_valid = value.lower() in [a.lower() for a in self._allowed]

        if is_valid:
            return SpecResult.ok(
                self.rule_id,
                f"{self._field}='{value}' is valid",
                tags=self.tags,
                data={"value": value, "allowed": self._allowed}
            )

        return SpecResult.fail(
            self.rule_id,
            f"{self._field}='{value}' not in allowed values: {self._allowed}",
            suggested_fix=f"Extract {self._field} as one of: {', '.join(self._allowed)}",
            tags=self.tags,
            data={
                "value": value,
                "allowed": self._allowed,
                "case_sensitive": self._case_sensitive
            }
        )


class ProgressSpec(Spec):
    """
    Anti-loop spec: Validates that the situation has changed between retries.

    This prevents blind retries by checking that at least ONE thing changed:
    - New field appeared
    - Existing field value changed
    - Field count increased
    """

    @property
    def rule_id(self) -> str:
        return "extraction_progress"

    @property
    def tags(self) -> tuple[str, ...]:
        return ("progress", "anti-loop")

    def evaluate(self, context: Context, candidate: Any = None) -> SpecResult:
        """
        Check if extraction made progress compared to previous attempt.

        Looks for 'last_extraction' in context.data - if present,
        compares with current candidate to ensure progress.
        """
        if not isinstance(candidate, dict):
            # If candidate isn't a dict, can't check progress
            # But we don't fail - other specs will catch this
            return SpecResult.ok(
                self.rule_id,
                "No previous extraction to compare",
                tags=self.tags
            )

        last = context.get_data("last_extraction")

        if last is None or not isinstance(last, dict):
            # First attempt - no previous to compare
            return SpecResult.ok(
                self.rule_id,
                "First extraction attempt",
                tags=self.tags,
                data={"first_attempt": True}
            )

        # Check for progress:
        # 1. More fields extracted?
        new_field_count = len(candidate)
        old_field_count = len(last)

        if new_field_count > old_field_count:
            return SpecResult.ok(
                self.rule_id,
                f"Progress: {new_field_count} fields (was {old_field_count})",
                tags=self.tags,
                data={"new_fields": new_field_count - old_field_count}
            )

        # 2. Any field value changed?
        changed_fields = []
        for key in candidate:
            if key not in last or candidate[key] != last[key]:
                changed_fields.append(key)

        if changed_fields:
            return SpecResult.ok(
                self.rule_id,
                f"Progress: {len(changed_fields)} fields changed",
                tags=self.tags,
                data={"changed_fields": changed_fields}
            )

        # No progress - identical extraction
        return SpecResult.fail(
            self.rule_id,
            "No progress: extraction identical to previous attempt",
            suggested_fix="Try different extraction strategy or enrichment",
            tags=self.tags,
            data={
                "candidate": candidate,
                "last": last,
                "identical": True
            }
        )
