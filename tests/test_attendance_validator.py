"""Tests for the attendance validator (CE credit eligibility rules)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.models.participant import (
    AttendanceRecord,
    ParticipantAttendance,
)
from src.validator.attendance import (
    AttendanceResult,
    validate_all,
    validate_attendance,
)

SESSION_START = datetime(2026, 3, 20, 9, 0, 0, tzinfo=UTC)
SESSION_END = datetime(2026, 3, 20, 12, 0, 0, tzinfo=UTC)


def _make_record(
    name: str = "Test Person",
    join_offset: int = 0,
    leave_offset: int = 180,
) -> AttendanceRecord:
    """Build an AttendanceRecord with join/leave at SESSION_START + offset (minutes)."""
    return AttendanceRecord(
        name_raw=name,
        email=None,
        join_time=SESSION_START + timedelta(minutes=join_offset),
        leave_time=SESSION_START + timedelta(minutes=leave_offset),
        duration_minutes=max(0, leave_offset - join_offset),
        is_guest=False,
        is_waiting_room=False,
    )


def _make_participant(
    name: str = "Test Person",
    records: list[AttendanceRecord] | None = None,
) -> ParticipantAttendance:
    """Build a ParticipantAttendance from records or a single full-session record."""
    if records is None:
        records = [_make_record(name)]
    return ParticipantAttendance.from_records(records)


def test_eligible_full_attendance() -> None:
    """Given a participant present for the entire session (0 late, 0 early, 0 gaps),
    validate_attendance returns eligible."""
    p = _make_participant()

    result = validate_attendance(p, SESSION_START, SESSION_END)

    assert result.is_eligible
    assert result.late_join_minutes == 0.0
    assert result.early_leave_minutes == 0.0
    assert result.mid_session_gaps_minutes == 0.0
    assert result.total_missed_minutes == 0.0
    assert result.failure_reason is None


def test_ineligible_late_join() -> None:
    """Given a participant who joined 16 minutes late, validate_attendance returns
    not eligible (> 15 min grace period)."""
    p = _make_participant(records=[_make_record(join_offset=16)])

    result = validate_attendance(p, SESSION_START, SESSION_END)

    assert not result.is_eligible
    assert result.late_join_minutes == 16.0
    assert result.early_leave_minutes == 0.0
    assert result.total_missed_minutes == 16.0
    assert result.failure_reason is not None
    failure = result.failure_reason  # narrows type for basedpyright
    assert "late join" in failure.lower()


def test_ineligible_early_leave() -> None:
    """Given a participant who left 16 minutes early, validate_attendance returns
    not eligible (> 15 min grace period)."""
    p = _make_participant(records=[_make_record(leave_offset=164)])  # 180 - 164 = 16 min early

    result = validate_attendance(p, SESSION_START, SESSION_END)

    assert not result.is_eligible
    assert result.early_leave_minutes == 16.0
    assert result.late_join_minutes == 0.0
    assert result.failure_reason is not None
    failure_early = result.failure_reason
    assert "early leave" in failure_early.lower()


def test_ineligible_mid_session_gaps() -> None:
    """Given 10 min late + 10 min gap = 20 min total missed (> 15), not eligible."""
    p = _make_participant(
        records=[
            _make_record(join_offset=10, leave_offset=40),  # joined 10 min late
            _make_record(join_offset=50, leave_offset=180),  # 10 min gap
        ]
    )

    result = validate_attendance(p, SESSION_START, SESSION_END)

    assert not result.is_eligible
    # late_join: 10, gaps: 50 - 40 = 10, total = 20
    assert result.late_join_minutes == 10.0
    assert result.mid_session_gaps_minutes == 10.0
    assert result.total_missed_minutes == 20.0


def test_eligible_mixed() -> None:
    """Given 5 min late + 5 min gap + 3 min early = 13 min total (< 15), eligible."""
    p = _make_participant(
        records=[
            _make_record(join_offset=5, leave_offset=60),  # 5 min late
            _make_record(join_offset=65, leave_offset=177),  # 5 min gap, 3 min early (180-177)
        ]
    )

    result = validate_attendance(p, SESSION_START, SESSION_END)

    assert result.is_eligible
    assert result.late_join_minutes == 5.0
    assert result.mid_session_gaps_minutes == 5.0
    assert result.early_leave_minutes == 3.0
    assert result.total_missed_minutes == 13.0
    assert result.failure_reason is None


def test_edge_case_full_missed() -> None:
    """Given a participant with no non-waiting-room segments, total_missed = full
    session duration and they are ineligible."""
    # A participant who only had waiting-room records would be skipped by the parser,
    # but if validate_attendance receives one with empty segments, it handles it.
    p = ParticipantAttendance(
        name_raw="Ghost",
        segments=(),
        first_join=SESSION_START,
        last_leave=SESSION_END,
        total_attended_minutes=0,  # pyright: ignore[reportArgumentType]  # test-only construction
    )

    result = validate_attendance(p, SESSION_START, SESSION_END)

    assert not result.is_eligible
    assert result.total_attended_minutes == 0
    assert result.total_missed_minutes == 180.0  # 3 hours
    assert result.failure_reason is not None


def test_zero_duration_session() -> None:
    """Given session_start == session_end, attendance is evaluated without crashing.
    A participant on time has 0 late, 0 early, 0 total missed."""
    start = datetime(2026, 3, 20, 9, 0, tzinfo=UTC)
    p = _make_participant(records=[_make_record(join_offset=0, leave_offset=0)])

    result = validate_attendance(p, start, start)

    assert result.is_eligible
    assert result.late_join_minutes == 0.0
    assert result.early_leave_minutes == 0.0
    assert result.total_missed_minutes == 0.0


def test_validate_all() -> None:
    """Given a list of participants, validate_all returns a dict keyed by normalized
    name with corresponding AttendanceResult values."""
    p1 = _make_participant(name="Alice Jones")
    p2 = _make_participant(
        name="Bob Smith",
        records=[_make_record(join_offset=20, name="Bob Smith")],
    )

    results = validate_all([p1, p2], SESSION_START, SESSION_END)

    assert "alice jones" in results
    assert "bob smith" in results
    assert results["alice jones"].is_eligible
    assert not results["bob smith"].is_eligible
    assert isinstance(results["alice jones"], AttendanceResult)
    assert isinstance(results["bob smith"], AttendanceResult)
