"""Attendance is judged only inside the session window (synthetic data)."""

from __future__ import annotations

from datetime import datetime

from src.models.participant import AttendanceRecord, ParticipantAttendance
from src.validator.attendance import validate_attendance

START = datetime(2026, 11, 2, 9, 0)
END = datetime(2026, 11, 2, 12, 0)


def _person(*spans: tuple[tuple[int, int], tuple[int, int]]) -> ParticipantAttendance:
    records = [
        AttendanceRecord(
            name_raw="Riley Stone",
            email="riley@example.test",
            join_time=datetime(2026, 11, 2, *join),
            leave_time=datetime(2026, 11, 2, *leave),
            duration_minutes=int(
                (datetime(2026, 11, 2, *leave) - datetime(2026, 11, 2, *join)).total_seconds()
                // 60
            ),
            is_guest=False,
            is_waiting_room=False,
        )
        for join, leave in spans
    ]
    return ParticipantAttendance.from_records(records)


def test_reconnect_before_the_session_starts_is_not_a_gap() -> None:
    result = validate_attendance(_person(((8, 30), (8, 40)), ((9, 0), (12, 0))), START, END)
    assert result.is_eligible, result.failure_reason
    assert result.mid_session_gaps_minutes == 0.0
    assert result.total_missed_minutes == 0.0


def test_reconnect_after_the_session_ends_is_not_a_gap() -> None:
    result = validate_attendance(_person(((9, 0), (12, 0)), ((12, 20), (12, 30))), START, END)
    assert result.is_eligible, result.failure_reason
    assert result.early_leave_minutes == 0.0


def test_real_gap_inside_the_session_still_counts() -> None:
    result = validate_attendance(_person(((8, 30), (10, 0)), ((10, 20), (12, 0))), START, END)
    assert not result.is_eligible
    assert result.mid_session_gaps_minutes == 20.0


def test_overlapping_segments_do_not_hide_a_gap() -> None:
    # Two devices: one 9:00-10:30, another 9:10-10:00, then back at 10:50.
    result = validate_attendance(
        _person(((9, 0), (10, 30)), ((9, 10), (10, 0)), ((10, 50), (12, 0))), START, END
    )
    assert result.mid_session_gaps_minutes == 20.0
    assert not result.is_eligible


def test_attendance_only_outside_the_window_is_ineligible() -> None:
    result = validate_attendance(_person(((7, 0), (8, 0))), START, END)
    assert not result.is_eligible
    assert result.total_missed_minutes == 180.0
