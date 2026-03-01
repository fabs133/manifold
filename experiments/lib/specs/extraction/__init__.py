"""
Data extraction specs for validating structured data extraction tasks.

These specs validate:
- Required fields presence
- Email format validation
- Numeric range validation
- Enum/choice validation
- Schema compliance
"""

from .specs import (
    HasRequiredFieldsSpec,
    EmailValidationSpec,
    RangeValidationSpec,
    EnumValidationSpec,
    ProgressSpec,
)

__all__ = [
    "HasRequiredFieldsSpec",
    "EmailValidationSpec",
    "RangeValidationSpec",
    "EnumValidationSpec",
    "ProgressSpec",
]
