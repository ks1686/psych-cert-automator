"""Attendance validator — determines CE credit eligibility from Zoom data."""

from src.validator.attendance import (
    AttendanceResult,
    validate_all,
    validate_attendance,
)

__all__ = [
    "AttendanceResult",
    "validate_all",
    "validate_attendance",
]
