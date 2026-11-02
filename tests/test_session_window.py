"""Eligibility uses the entered session times, not the Zoom meeting window."""

from __future__ import annotations

import asyncio
from datetime import date, time
from typing import TYPE_CHECKING

import pytest
from src import pipeline
from src.backends.routes import MatchRequest, match_endpoint
from src.pipeline import run_pipeline

from tests.synthetic import at, seg, write_qualtrics, write_zoom

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def early_host_files(tmp_path: Path) -> tuple[Path, Path]:
    """Host opened the meeting at 8:30 and ended it at 12:15; session was 9-12."""
    zoom = write_zoom(
        tmp_path / "zoom.xlsx",
        [
            seg("Hana Host", "hana.host@example.test", at(8, 30), at(12, 15)),
            seg("Olive Ontime", "olive@example.test", at(8, 58), at(12, 1)),
        ],
        meeting_start=at(8, 30),
        meeting_end=at(12, 15),
    )
    qualtrics = write_qualtrics(
        tmp_path / "qualtrics.xlsx",
        [("Olive Ontime", "olive@example.test", "Psychologist (APA)", None)],
    )
    return zoom, qualtrics


def test_generate_uses_entered_session_times(
    early_host_files: tuple[Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    zoom, qualtrics = early_host_files
    monkeypatch.setattr(
        pipeline,
        "generate_all",
        lambda outputs, _dir, **_kw: [str(tmp_path / f"{i}.pdf") for i in range(len(outputs))],
    )
    result = run_pipeline(
        str(zoom),
        str(qualtrics),
        "Synthetic CE Workshop",
        date(2026, 11, 2),
        "Pat Presenter",
        3,
        ["APA"],
        time(9, 0),
        time(12, 0),
        output_dir=str(tmp_path / "out"),
    )
    assert result.errors == []
    assert [c.full_name for c in result.eligible] == ["Olive Ontime"]
    assert result.ineligible == []


def test_match_uses_entered_session_times(early_host_files: tuple[Path, Path]) -> None:
    zoom, _ = early_host_files
    request = MatchRequest.model_validate(
        {
            "zoom_path": str(zoom),
            "zoom_participants": [],
            "ce_requests": [
                {"name_on_certificate": "Olive Ontime", "ce_type": "Psychologist (APA)"},
            ],
            # The UI sends the Zoom meeting window plus the typed times.
            "session_start": at(8, 30).isoformat(),
            "session_end": at(12, 15).isoformat(),
            "start_time": "09:00",
            "end_time": "12:00",
        }
    )
    response = asyncio.run(match_endpoint(request))
    entry = response.matches[0]
    assert entry.attendance is not None
    assert entry.attendance["is_eligible"] is True
    assert entry.attendance["late_join"] == 0.0
    assert entry.attendance["early_leave"] == 0.0


def test_entered_times_still_reject_a_real_late_join(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    zoom = write_zoom(
        tmp_path / "zoom.xlsx",
        [seg("Lou Late", "lou@example.test", at(9, 20), at(12, 0))],
        meeting_start=at(8, 30),
        meeting_end=at(12, 15),
    )
    qualtrics = write_qualtrics(
        tmp_path / "q.xlsx", [("Lou Late", "lou@example.test", "Psychologist (APA)", None)]
    )
    monkeypatch.setattr(pipeline, "generate_all", lambda outputs, _dir, **_kw: [])
    result = run_pipeline(
        str(zoom), str(qualtrics), "T", date(2026, 11, 2), "P", 3, ["APA"],
        time(9, 0), time(12, 0), output_dir=str(tmp_path / "out"),
    )
    assert result.eligible == []
    assert result.ineligible[0].late_join_minutes == 20
