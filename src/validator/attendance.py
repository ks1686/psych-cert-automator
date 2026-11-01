"""Zoom attendance validator — CE credit eligibility rules.

Determines whether a participant met the attendance requirements for CE credit
based on join/leave times relative to the session window.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from typing import TYPE_CHECKING

from src.models.participant import ParticipantAttendance, normalize_name

if TYPE_CHECKING:
    from datetime import datetime, timedelta

    from src.models.participant import AttendanceRecord

# ── Constants ──────────────────────────────────────────────────────────────────

_GRACE_MINUTES: float = 15.0
"""Maximum allowed late join, early leave, or total missed time in minutes."""

_SESSION_DURATION_MSG = "entire session"
"""Label used in failure messages when no attendance segments exist."""


# ── Result type ────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class AttendanceResult:
    """Outcome of validating one participant's Zoom attendance against CE rules.

    Every minute field is rounded to one decimal place. ``total_attended_minutes``
    is an integer (sum of segment durations from Zoom's own reporting).
    """

    is_eligible: bool
    """Whether the participant qualifies for CE credit."""

    late_join_minutes: float
    """Minutes between session start and first join (0.0 if on time)."""

    early_leave_minutes: float
    """Minutes between last leave and session end (0.0 if stayed to end)."""

    mid_session_gaps_minutes: float
    """Sum of gaps (in minutes) between consecutive leave/join pairs."""

    total_missed_minutes: float
    """Sum of late_join + early_leave + mid_session_gaps."""

    total_attended_minutes: int
    """Sum of Zoom-reported segment durations."""

    failure_reason: str | None
    """Human-readable explanation of which rule(s) failed, or ``None`` if eligible."""


# ── Core validation ────────────────────────────────────────────────────────────


def validate_attendance(
    participant: ParticipantAttendance,
    session_start: datetime,
    session_end: datetime,
) -> AttendanceResult:
    """Validate a participant's attendance against CE eligibility rules.

    Rules (all thresholds are 15.0 minutes):
        1. First join time must be ≤ 15 minutes after session start.
        2. Last leave time must be ≥ 15 minutes before session end.
        3. Total missed time (late join + early leave + mid-session gaps)
           must be ≤ 15 minutes.

    Only time inside ``[session_start, session_end]`` counts: segments are
    clipped to the window and overlapping segments (two devices) are merged
    before late join, early leave, and gaps are measured. A reconnect before
    the session starts or after it ends is therefore never a gap.

    Args:
        participant: Aggregated attendance data for one person.
        session_start: Official session start datetime.
        session_end: Official session end datetime.

    Returns:
        ``AttendanceResult`` with eligibility determination and detailed metrics.
    """
    spans = _spans_in_window(participant.segments, session_start, session_end)

    if not spans:
        return _result_when_no_segments(session_start, session_end)

    late_join = _clamp_to_positive_minutes(spans[0][0] - session_start)
    early_leave = _clamp_to_positive_minutes(session_end - spans[-1][1])

    total_gaps = sum(
        _minutes_between(prev_end, next_start)
        for (_, prev_end), (next_start, _) in pairwise(spans)
    )

    total_missed = round(late_join + early_leave + total_gaps, 1)

    is_eligible = (
        late_join <= _GRACE_MINUTES
        and early_leave <= _GRACE_MINUTES
        and total_missed <= _GRACE_MINUTES
    )

    failure_reason = (
        None
        if is_eligible
        else _build_failure_reason(late_join, early_leave, total_gaps, total_missed)
    )

    return AttendanceResult(
        is_eligible=is_eligible,
        late_join_minutes=round(late_join, 1),
        early_leave_minutes=round(early_leave, 1),
        mid_session_gaps_minutes=round(total_gaps, 1),
        total_missed_minutes=total_missed,
        total_attended_minutes=int(participant.total_attended_minutes),
        failure_reason=failure_reason,
    )


# ── Bulk validation ────────────────────────────────────────────────────────────


def validate_all(
    participants: list[ParticipantAttendance],
    session_start: datetime,
    session_end: datetime,
) -> dict[str, AttendanceResult]:
    """Validate every participant in a list, keyed by normalized name.

    Each participant's name is normalized via ``normalize_name()`` before
    being used as the dictionary key. If two participants normalize to the
    same key, later entries overwrite earlier ones (callers are responsible
    for deduplication if that matters).

    Args:
        participants: List of participants to validate.
        session_start: Official session start datetime.
        session_end: Official session end datetime.

    Returns:
        Dictionary mapping normalized name → ``AttendanceResult``.
    """
    return {
        normalize_name(p.name_raw): validate_attendance(p, session_start, session_end)
        for p in participants
    }


# ── Helpers ────────────────────────────────────────────────────────────────────


def _minutes_between(start: datetime, end: datetime) -> float:
    """Return the number of minutes between two datetimes as a float."""
    return (end - start).total_seconds() / 60.0


def _clamp_to_positive_minutes(td: timedelta) -> float:
    """Return ``td`` in minutes, clamping negative values to 0.0.

    Args:
        td: The timedelta to convert (e.g., ``join_time - session_start``).

    Returns:
        Positive minutes as a float, or 0.0 if the timedelta is negative.
    """
    minutes = td.total_seconds() / 60.0
    return minutes if minutes > 0 else 0.0


def _spans_in_window(
    segments: tuple[AttendanceRecord, ...],
    session_start: datetime,
    session_end: datetime,
) -> list[tuple[datetime, datetime]]:
    """Clip segments to the session window and merge overlaps, in time order."""
    clipped = sorted(
        (max(seg.join_time, session_start), min(seg.leave_time, session_end))
        for seg in segments
        if not seg.is_waiting_room
    )
    # A zero-length window (start == end) still accepts a segment touching it.
    zero_window = session_end <= session_start
    merged: list[tuple[datetime, datetime]] = []
    for start, end in clipped:
        if end < start or (end == start and not zero_window):
            continue
        if merged and start <= merged[-1][1]:
            if end > merged[-1][1]:
                merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))
    return merged


def _result_when_no_segments(
    session_start: datetime,
    session_end: datetime,
) -> AttendanceResult:
    """Build an ``AttendanceResult`` for a participant with zero attendance segments.

    The participant is marked ineligible, and ``total_missed_minutes`` equals
    the full session duration.
    """
    full_duration = round(_minutes_between(session_start, session_end), 1)
    return AttendanceResult(
        is_eligible=False,
        late_join_minutes=full_duration,
        early_leave_minutes=0.0,
        mid_session_gaps_minutes=0.0,
        total_missed_minutes=full_duration,
        total_attended_minutes=0,
        failure_reason=_SESSION_DURATION_MSG,
    )


def _build_failure_reason(
    late_join: float,
    early_leave: float,
    total_gaps: float,
    total_missed: float,
) -> str:
    """Build a human-readable failure reason from the individual metrics.

    Reports each rule that was violated. If total missed exceeds the grace
    period purely due to the combination of late join and early leave (each
    individually within bounds), the individual entries are consolidated
    into the aggregate reason.

    Args:
        late_join: Late join minutes (raw, unrounded).
        early_leave: Early leave minutes (raw, unrounded).
        total_gaps: Mid-session gap minutes (raw, unrounded).
        total_missed: Total missed minutes (rounded to 1 decimal).

    Returns:
        A single-line description of which rule(s) were violated.
    """
    reasons: list[str] = []

    late_fails = late_join > _GRACE_MINUTES
    early_fails = early_leave > _GRACE_MINUTES
    total_fails = total_missed > _GRACE_MINUTES
    has_mid_gaps = total_gaps > 0

    if late_fails:
        reasons.append(f"late join ({late_join:.1f}m > {_GRACE_MINUTES:.0f}m)")

    if early_fails:
        reasons.append(f"early leave ({early_leave:.1f}m > {_GRACE_MINUTES:.0f}m)")

    if has_mid_gaps:
        reasons.append(f"mid-session gaps ({total_gaps:.1f}m)")

    if total_fails:
        reasons.append(
            f"total missed ({total_missed:.1f}m > {_GRACE_MINUTES:.0f}m)",
        )

    if not reasons:
        return _SESSION_DURATION_MSG

    return "; ".join(reasons)
