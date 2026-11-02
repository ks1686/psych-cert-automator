"""Zoom attendees who share a display name are kept apart by email."""

from __future__ import annotations

from datetime import date, time
from typing import TYPE_CHECKING

import src.pipeline as pipeline
from src.models.certificate import EligibilityStatus
from src.parser.zoom import parse_zoom_attendance
from src.pipeline import run_pipeline

from tests.synthetic import at, seg, write_qualtrics, write_zoom

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

APA = "Psychologist (APA)"


def _zoom(tmp_path: Path) -> Path:
    return write_zoom(
        tmp_path / "z.xlsx",
        [
            seg("Chris Park", "chris.p1@example.test", at(9, 0), at(12, 0)),
            seg("Chris Park", "chris.p2@example.test", at(9, 0), at(9, 40)),
            seg("Dee Ray", "dee@example.test", at(9, 0), at(10, 0)),
            seg("Dee Ray", None, at(10, 0), at(12, 0)),
        ],
    )


def test_same_name_different_email_are_two_people(tmp_path: Path) -> None:
    session = parse_zoom_attendance(str(_zoom(tmp_path)))
    by_name = {p.name_raw: p for p in session.participants}
    assert set(by_name) == {
        "Chris Park (chris.p1@example.test)",
        "Chris Park (chris.p2@example.test)",
        "Dee Ray",
    }
    assert by_name["Chris Park (chris.p1@example.test)"].total_attended_minutes == 180
    assert by_name["Chris Park (chris.p2@example.test)"].total_attended_minutes == 40
    # A reconnect without an email still belongs to the only Dee Ray.
    assert by_name["Dee Ray"].total_attended_minutes == 180


def test_a_chris_who_left_early_is_not_credited_with_the_other_chris(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    qualtrics = write_qualtrics(
        tmp_path / "q.xlsx",
        [("Chris Park", "Chris.P2@example.test", APA, None)],
    )
    monkeypatch.setattr(
        pipeline, "generate_all", lambda outputs, _d, **_k: [f"{i}.pdf" for i in range(len(outputs))]
    )
    result = run_pipeline(
        str(_zoom(tmp_path)), str(qualtrics), "T", date(2026, 11, 2), "P", 3,
        ["APA"], time(9, 0), time(12, 0), output_dir=str(tmp_path / "out"),
    )
    # Before: both rows merged into one 9:00-12:00 Chris Park, who passed.
    assert result.eligible == []
    [entry] = result.ineligible
    assert entry.status is EligibilityStatus.ATTENDANCE_INSUFFICIENT
    assert entry.name_zoom == "Chris Park (chris.p2@example.test)"
