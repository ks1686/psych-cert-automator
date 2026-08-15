"""Training metadata model — parsed from configuration input at the boundary."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from typing import ClassVar, NewType, NotRequired, TypedDict, override

from pydantic import BaseModel, ConfigDict

CEType = NewType("CEType", str)
"""Branded string type for CE type short codes (e.g., 'APA', 'NASP', 'NY')."""


class TrainingConfigDict(TypedDict):
    """Shape of a raw training configuration dictionary.

    Used as the input type for ``TrainingMetadata.from_config`` so the type
    checker can precisely infer the type of each key access.
    """

    title: str
    date: str
    instructor_name: str
    ce_credits: int
    ce_types_offered: list[str]
    session_start: str
    session_end: str
    end_date: NotRequired[str | None]
    is_virtual: NotRequired[bool]
    location: NotRequired[str | None]

@dataclass(frozen=True, slots=True)
class TrainingConfigError(Exception):
    """Error raised when training configuration is invalid.

    Carries the offending field name, its raw value, and a human-readable reason
    so callers can surface precise diagnostics.
    """

    field: str
    value: str
    reason: str

    @override
    def __str__(self) -> str:
        """Return a human-readable error message."""
        return f"Training config error: {self.field}={self.value!r} — {self.reason}"


class TrainingMetadata(BaseModel):
    """Training session metadata parsed from configuration input.

    This is the boundary type — raw config enters via ``from_config``, and
    downstream code receives a fully validated, typed object.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    title: str
    """Title of the training session."""

    date: date
    """Date the training occurred."""

    instructor_name: str
    """Name of the instructor."""

    ce_credits: int
    """Number of CE credits awarded for full attendance."""

    ce_types_offered: frozenset[CEType]
    """Short codes for CE types offered (e.g., {'APA', 'NASP', 'NY'})."""

    session_start: time
    """Session start time (local)."""

    session_end: time
    """Session end time (local)."""

    end_date: date | None = None
    """Optional multi-day end date (inclusive)."""

    is_virtual: bool = True
    """When True, certificates use virtual Location/Format strings."""

    location: str | None = None
    """In-person location text when ``is_virtual`` is False."""

    @property
    def total_duration_minutes(self) -> int:
        """Total session duration in minutes (session_end minus session_start)."""
        start_mins = self.session_start.hour * 60 + self.session_start.minute
        end_mins = self.session_end.hour * 60 + self.session_end.minute
        return end_mins - start_mins

    @property
    def is_multi_day(self) -> bool:
        """True when an end date is set and differs from the start date."""
        return self.end_date is not None and self.end_date != self.date

    @classmethod
    def from_config(cls, config: TrainingConfigDict) -> TrainingMetadata:
        """Parse training metadata from a raw configuration dictionary.

        Args:
            config: Raw key-value map matching the ``TrainingConfigDict`` shape.

        Returns:
            A fully validated ``TrainingMetadata`` instance.

        Raises:
            TrainingConfigError: If any field contains an unparseable value
                (e.g., invalid date or time format) or violates constraints.
        """
        title = config["title"]
        instructor = config["instructor_name"]

        ce_credit_count = config["ce_credits"]
        if ce_credit_count < 1:
            raise TrainingConfigError(
                field="ce_credits",
                value=str(ce_credit_count),
                reason="must be >= 1",
            )

        ce_types_raw = config["ce_types_offered"]
        if not ce_types_raw:
            raise TrainingConfigError(
                field="ce_types_offered",
                value=str(ce_types_raw),
                reason="must not be empty",
            )
        ce_types: frozenset[CEType] = frozenset(CEType(str(t)) for t in ce_types_raw)

        date_str = config["date"]
        try:
            parsed_date = date.fromisoformat(date_str)
        except (ValueError, TypeError) as e:
            raise TrainingConfigError(
                field="date",
                value=date_str,
                reason=f"invalid date (expected YYYY-MM-DD): {e}",
            ) from e

        start_str = config["session_start"]
        try:
            parsed_start = time.fromisoformat(start_str)
        except (ValueError, TypeError) as e:
            raise TrainingConfigError(
                field="session_start",
                value=start_str,
                reason=f"invalid time (expected HH:MM): {e}",
            ) from e

        end_str = config["session_end"]
        try:
            parsed_end = time.fromisoformat(end_str)
        except (ValueError, TypeError) as e:
            raise TrainingConfigError(
                field="session_end",
                value=end_str,
                reason=f"invalid time (expected HH:MM): {e}",
            ) from e

        parsed_end_date: date | None = None
        end_date_raw = config.get("end_date")
        if end_date_raw:
            try:
                parsed_end_date = date.fromisoformat(end_date_raw)
            except (ValueError, TypeError) as e:
                raise TrainingConfigError(
                    field="end_date",
                    value=str(end_date_raw),
                    reason=f"invalid date (expected YYYY-MM-DD): {e}",
                ) from e
            if parsed_end_date < parsed_date:
                raise TrainingConfigError(
                    field="end_date",
                    value=str(end_date_raw),
                    reason="must be on or after date",
                )

        is_virtual = config.get("is_virtual", True)
        location_raw = config.get("location")
        location = location_raw.strip() if isinstance(location_raw, str) and location_raw.strip() else None
        if not is_virtual and not location:
            raise TrainingConfigError(
                field="location",
                value=str(location_raw),
                reason="required for in-person events",
            )

        return cls(
            title=title,
            date=parsed_date,
            instructor_name=instructor,
            ce_credits=ce_credit_count,
            ce_types_offered=ce_types,
            session_start=parsed_start,
            session_end=parsed_end,
            end_date=parsed_end_date,
            is_virtual=is_virtual,
            location=location,
        )
