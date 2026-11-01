"""When Zoom ran shorter than the entered session, judge the overlap and warn."""

from __future__ import annotations

import asyncio
from datetime import date, time
from typing import TYPE_CHECKING

import pytest
from src import pipeline
from src.backends.routes import MatchRequest, match_endpoint
from src.pipeline import run_pipeline, session_window

from tests.synthetic import at, seg, write_qualtrics, write_zoom

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def ended_early(tmp_path: Path) -> tuple[Path, Path]:
    """Session entered as 9:00-12:00; the host ended the Zoom meeting at 11:40."""
    zoom = write_zoom(
        tmp_path / "zoom.xlsx",
        [
            seg("Hana Host", "hana.host@example.test", at(8, 50), at(11, 40)),
            seg("Olive Ontime", "olive@example.test", at(8, 58), at(11, 40)),
            seg("Lou Late", "lou@example.test", at(9, 30), at(11, 40)),
        ],
        meeting_start=at(8, 50),
        meeting_end=at(11, 40),
    )
    qualtrics = write_qualtrics(
        tmp_path / "qualtrics.xlsx",
        [
            ("Olive Ontime", "olive@example.test", "Psychologist (APA)", None),
            ("Lou Late", "lou@example.test", "Psychologist (APA)", None),
        ],
    )
    return zoom, qualtrics


def test_window_is_the_overlap_of_entered_and_zoom_times() -> None:
    start, end = session_window(at(8, 50), at(11, 40), time(9, 0), time(12, 0))
    assert (start, end) == (at(9, 0), at(11, 40))


def test_pipeline_judges_the_overlap_and_warns(
    ended_early: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    zoom, qualtrics = ended_early
    monkeypatch.setattr(
        pipeline, "generate_all", lambda outputs, _d, **_k: [f"{i}.pdf" for i in range(len(outputs))]
    )
    result = run_pipeline(
        str(zoom), str(qualtrics), "T", date(2026, 11, 2), "P", 3, ["APA"],
        time(9, 0), time(12, 0), output_dir=str(tmp_path / "out"),
    )
    assert [c.full_name for c in result.eligible] == ["Olive Ontime"]
    assert [e.name_qualtrics for e in result.ineligible] == ["Lou Late"]
    assert result.ineligible[0].early_leave_minutes == 0
    assert any("11:40" in w and "12:00" in w for w in result.warnings), result.warnings


def test_match_judges_the_overlap_and_warns(ended_early: tuple[Path, Path]) -> None:
    zoom, _ = ended_early
    request = MatchRequest.model_validate(
        {
            "zoom_path": str(zoom),
            "zoom_participants": [],
            "ce_requests": [
                {"name_on_certificate": "Olive Ontime", "ce_type": "Psychologist (APA)"},
            ],
            "session_start": at(8, 50).isoformat(),
            "session_end": at(11, 40).isoformat(),
            "start_time": "09:00",
            "end_time": "12:00",
        }
    )
    response = asyncio.run(match_endpoint(request))
    assert response.matches[0].attendance is not None
    assert response.matches[0].attendance["is_eligible"] is True
    assert any("11:40" in w for w in response.warnings)
