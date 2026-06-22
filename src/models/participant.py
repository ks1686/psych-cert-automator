"""Zoom participant and attendance data models — internal value objects."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, NewType, override

if TYPE_CHECKING:
    from datetime import datetime


Minutes = NewType("Minutes", int)
"""Branded integer type for minute durations."""


@dataclass(frozen=True, slots=True)
class ParticipantDataError(Exception):
    """Error for invalid participant or attendance data.

    Carries the raw name involved and a human-readable reason so callers can
    surface precise diagnostics.
    """

    name_raw: str
    reason: str

    @override
    def __str__(self) -> str:
        """Return a human-readable error message."""
        return f"Participant data error for {self.name_raw!r}: {self.reason}"


@dataclass(frozen=True, slots=True)
class AttendanceRecord:
    """One Zoom join/leave segment for a participant."""

    name_raw: str
    """Original name as reported by Zoom (may include titles, pronouns, etc.)."""

    email: str | None
    """Email associated with the participant. Often empty for guests."""

    join_time: datetime
    """When the participant joined this segment."""

    leave_time: datetime
    """When the participant left this segment."""

    duration_minutes: int
    """Duration of this specific segment in minutes."""

    is_guest: bool
    """Whether this participant joined as a guest."""

    is_waiting_room: bool
    """Whether this segment represents time spent in the waiting room.

    Waiting-room segments are excluded from attendance computation.
    """


@dataclass(frozen=True, slots=True)
class ParticipantAttendance:
    """Aggregated attendance data for one person across all Zoom segments."""

    name_raw: str
    """Original name from Zoom (from the first non-waiting-room segment)."""

    segments: tuple[AttendanceRecord, ...]
    """Non-waiting-room segments, sorted by join_time ascending."""

    first_join: datetime
    """Earliest join time across all non-waiting-room segments."""

    last_leave: datetime
    """Latest leave time across all non-waiting-room segments."""

    total_attended_minutes: Minutes
    """Sum of duration_minutes across all non-waiting-room segments."""

    @classmethod
    def from_records(cls, records: list[AttendanceRecord]) -> ParticipantAttendance:
        """Build aggregated attendance from a list of raw segment records.

        Filters out waiting-room segments and sorts by join time. Raises
        ``ParticipantDataError`` if no valid segments remain after filtering.

        Args:
            records: Raw per-segment records for one person (may include
                waiting-room entries).

        Returns:
            Aggregated attendance with computed first_join, last_leave, and
            total_attended_minutes.

        Raises:
            ParticipantDataError: If all records are waiting-room entries
                (i.e., no real attendance data remains).
        """
        valid_segments = sorted(
            (r for r in records if not r.is_waiting_room),
            key=lambda r: r.join_time,
        )

        if not valid_segments:
            name = records[0].name_raw if records else "<unknown>"
            raise ParticipantDataError(
                name_raw=name,
                reason="no non-waiting-room attendance records",
            )

        first_join = min(r.join_time for r in valid_segments)
        last_leave = max(r.leave_time for r in valid_segments)
        total = sum(r.duration_minutes for r in valid_segments)

        return cls(
            name_raw=valid_segments[0].name_raw,
            segments=tuple(valid_segments),
            first_join=first_join,
            last_leave=last_leave,
            total_attended_minutes=Minutes(total),
        )


# ── Name normalisation utilities ─────────────────────────────────────────────


_TITLE_PATTERN = re.compile(
    r"\b(?:Dr|Ph\.?D|Psy\.?D|M\.?D|M\.?S\.?W|L\.?C\.?S\.?W"
    + r"|L\.?P\.?C|LMFT|LCSW|LPC|Ed\.?D|J\.?D|M\.?A|M\.?Ed"
    + r"|M\.?S|M\.?B\.?A|R\.?N|B\.?S\.?N|N\.?P|P\.?A)"
    + r"\.?\b",
    re.IGNORECASE,
)
"""Pattern matching common professional titles and credentials."""

_PAREN_CONTENT = re.compile(r"\([^)]*\)")
"""Pattern matching parenthetical content (including nested)."""

_WHITESPACE = re.compile(r"\s+")
"""Pattern matching runs of whitespace."""


def normalize_name(raw: str) -> str:
    """Normalize a raw Zoom participant name for matching purposes.

    Normalization steps (in order):
        1. Strip parenthetical content (pronouns, display names, notes).
        2. Strip professional titles and credentials (Dr., Ph.D., etc.).
        3. Remove the ``#`` character (Zoom guest indicator).
        4. Collapse whitespace and strip.
        5. Lowercase.

    Args:
        raw: The original name string from Zoom (e.g.,
            ``"Dr. Patricia A. Farrell"``, ``"Jaimee Arnoff# Ph.D. (she/her)"``).

    Returns:
        Normalized, lowercase name tokens joined by single spaces
        (e.g., ``"patricia a farrell"``, ``"jaimee arnoff"``).
    """
    cleaned = _PAREN_CONTENT.sub(" ", raw)
    cleaned = _TITLE_PATTERN.sub(" ", cleaned)
    cleaned = cleaned.replace("#", " ")
    cleaned = _WHITESPACE.sub(" ", cleaned).strip()
    return cleaned.lower()


def extract_name_tokens(normalized: str) -> frozenset[str]:
    """Extract word-level tokens from an already-normalized name.

    Args:
        normalized: A name string already processed by ``normalize_name()``.

    Returns:
        Frozenset of lowercase word tokens (e.g.,
        ``frozenset({'patricia', 'a', 'farrell'})``).
    """
    return frozenset(normalized.split())
