"""Real-world export variations must parse, and bad files must give a 400."""

from __future__ import annotations

import asyncio
from datetime import date, time
from typing import TYPE_CHECKING

import pytest
import src.pipeline as pipeline
from fastapi import HTTPException
from src.backends.routes import ParseRequest, parse_endpoint
from src.parser.qualtrics import parse_qualtrics_export
from src.parser.zoom import parse_zoom_attendance
from src.pipeline import run_pipeline

from tests.synthetic import (
    at,
    seg,
    write_qualtrics,
    write_qualtrics_csv,
    write_zoom,
    write_zoom_csv,
)

if TYPE_CHECKING:
    from pathlib import Path

APA = "Psychologist (APA)"
ROWS = [
    ("Ada Lovelace", "ada@example.test", APA, None),
    ("Grace Hopper", "grace@example.test", APA, None),
]
SEGMENTS = [
    seg("Ada Lovelace", "ada@example.test", at(9, 0), at(12, 0)),
    seg("Grace Hopper", "grace@example.test", at(9, 5), at(11, 0)),
]


def test_zoom_report_with_an_extra_top_row(tmp_path: Path) -> None:
    session = parse_zoom_attendance(str(write_zoom(tmp_path / "z.xlsx", SEGMENTS, extra_top_row=True)))
    assert session.session_start == at(9, 0)
    assert session.session_end == at(12, 0)
    assert [p.name_raw for p in session.participants] == ["Ada Lovelace", "Grace Hopper"]
    assert session.host == "Hana Host"


def test_zoom_csv_export(tmp_path: Path) -> None:
    session = parse_zoom_attendance(str(write_zoom_csv(tmp_path / "z.csv", SEGMENTS)))
    assert session.session_start == at(9, 0)
    assert [p.name_raw for p in session.participants] == ["Ada Lovelace", "Grace Hopper"]
    assert session.participants[1].first_join == at(9, 5)
    assert session.participants[0].email == "ada@example.test"


def test_qualtrics_three_header_rows(tmp_path: Path) -> None:
    requests = parse_qualtrics_export(str(write_qualtrics(tmp_path / "q.xlsx", ROWS, three_header=True)))
    assert [r.name_on_certificate for r in requests] == ["Ada Lovelace", "Grace Hopper"]


def test_qualtrics_csv_export(tmp_path: Path) -> None:
    requests = parse_qualtrics_export(str(write_qualtrics_csv(tmp_path / "q.csv", ROWS)))
    assert [(r.name_on_certificate, str(r.ce_type)) for r in requests] == [
        ("Ada Lovelace", APA),
        ("Grace Hopper", APA),
    ]


def test_unfinished_qualtrics_responses_are_ignored(tmp_path: Path) -> None:
    path = write_qualtrics(tmp_path / "q.xlsx", ROWS, finished=[True, False])
    assert [r.name_on_certificate for r in parse_qualtrics_export(str(path))] == ["Ada Lovelace"]


def test_pipeline_runs_on_csv_and_shifted_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        pipeline, "generate_all", lambda outputs, _d, **_k: [f"{i}.pdf" for i in range(len(outputs))]
    )
    result = run_pipeline(
        str(write_zoom_csv(tmp_path / "z.csv", SEGMENTS)),
        str(write_qualtrics(tmp_path / "q.xlsx", ROWS, three_header=True)),
        "T", date(2026, 11, 2), "P", 3, ["APA"], time(9, 0), time(12, 0),
        output_dir=str(tmp_path / "out"),
    )
    assert result.errors == []
    assert [c.full_name for c in result.eligible] == ["Ada Lovelace"]


@pytest.mark.parametrize("name", ["zoom.txt", "zoom.xlsx"])
def test_unreadable_file_is_a_400_with_a_plain_message(tmp_path: Path, name: str) -> None:
    bad = tmp_path / name
    bad.write_text("this is not a spreadsheet", encoding="utf-8")
    qualtrics = write_qualtrics(tmp_path / "q.xlsx", ROWS)
    with pytest.raises(HTTPException) as caught:
        asyncio.run(parse_endpoint(ParseRequest(zoom_path=str(bad), qualtrics_path=str(qualtrics))))
    assert caught.value.status_code == 400
    assert "read" in str(caught.value.detail).lower()


def test_pipeline_reports_an_unreadable_file_as_an_error(tmp_path: Path) -> None:
    bad = tmp_path / "zoom.txt"
    bad.write_text("nope", encoding="utf-8")
    result = run_pipeline(
        str(bad), str(write_qualtrics(tmp_path / "q.xlsx", ROWS)),
        "T", date(2026, 11, 2), "P", 3, ["APA"], time(9, 0), time(12, 0),
        output_dir=str(tmp_path / "out"),
    )
    assert result.errors
