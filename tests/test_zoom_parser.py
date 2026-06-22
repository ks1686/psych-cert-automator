"""Tests for the Zoom attendance report parser."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from src.parser.zoom import ZoomParseError, parse_zoom_attendance

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE_ZOOM = FIXTURES / "sample_zoom.xlsx"


def test_parses_sample_file() -> None:
    """Given a valid Zoom attendance .xlsx, parse_zoom_attendance returns a ZoomSession
    with correct participant count, session start, and session end."""
    session = parse_zoom_attendance(str(SAMPLE_ZOOM))

    assert len(session.participants) == 15
    assert session.session_start == datetime(2026, 3, 20, 8, 47, 2)  # noqa: DTZ001
    assert session.session_end == datetime(2026, 3, 20, 12, 11, 14)  # noqa: DTZ001
    # Participants should be sorted by first_join ascending.
    for i in range(len(session.participants) - 1):
        assert session.participants[i].first_join <= session.participants[i + 1].first_join


def test_filters_waiting_room() -> None:
    """Given a sample with waiting-room rows, those rows are excluded from participants.
    The total segment count across all participants should equal the non-waiting-room rows."""
    session = parse_zoom_attendance(str(SAMPLE_ZOOM))
    total_segments = sum(len(p.segments) for p in session.participants)
    # We know from inspection: 36 raw rows, 17 waiting-room rows, 19 non-waiting-room.
    assert total_segments == 19
    for p in session.participants:
        for seg in p.segments:
            assert not seg.is_waiting_room


def test_groups_by_normalized_name() -> None:
    """Given two participants with different middle initials, their normalized names
    differ and they appear as separate ParticipantAttendance entries."""
    session = parse_zoom_attendance(str(SAMPLE_ZOOM))

    names = {p.name_raw for p in session.participants}
    assert "Dr. Patricia A. Farrell" in names
    assert "Dr. Patricia Farrell" in names
    assert len(names) == 15  # no merging of distinct names


def test_file_not_found() -> None:
    """Given a non-existent filepath, parse_zoom_attendance raises ZoomParseError
    with the filepath and a descriptive reason."""
    with pytest.raises(ZoomParseError) as exc_info:
        _ = parse_zoom_attendance("/nonexistent/path/file.xlsx")
    assert "nonexistent" in exc_info.value.reason or "not found" in exc_info.value.reason.lower()
    assert exc_info.value.filepath == "/nonexistent/path/file.xlsx"


def test_participant_total_attended() -> None:
    """Given Scott Simmons with 12 + 5 minute segments (waiting room excluded),
    total_attended_minutes equals 17."""
    session = parse_zoom_attendance(str(SAMPLE_ZOOM))

    scott = next(p for p in session.participants if p.name_raw == "Scott Simmons")
    assert scott.total_attended_minutes == 17
    assert len(scott.segments) == 2
    durations = [s.duration_minutes for s in scott.segments]
    assert sorted(durations) == [5, 12]
