"""Duplicate survey submissions must produce one certificate, from the latest."""

from __future__ import annotations

from datetime import date, time
from typing import TYPE_CHECKING

import src.pipeline as pipeline
from src.parser.qualtrics import parse_qualtrics_export
from src.pipeline import dedupe_requests, run_pipeline

from tests.synthetic import at, seg, write_qualtrics, write_zoom

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

APA = "Psychologist (APA)"
NY = "Psychologist (New York)"


def _qualtrics(tmp_path: Path) -> Path:
    # Recorded times are deliberately out of row order: "latest" means the
    # most recent submission, not the last row.
    return write_qualtrics(
        tmp_path / "q.xlsx",
        [
            ("Ann Lee", "ann@example.test", NY, "LATEST-111"),
            ("Ann Lee", "ann@example.test", NY, "OLD-000"),
            ("ann  LEE", "ann@example.test", APA, None),
            ("Ann M. Lee", "ANN@example.test", APA, None),
            ("Bo Diaz", "bo@example.test", APA, None),
            ("Bo Diaz", None, APA, None),
        ],
        recorded=[at(14, 0), at(13, 0), at(13, 5), at(13, 10), at(13, 0), at(13, 1)],
    )


def test_parser_reads_the_submission_time(tmp_path: Path) -> None:
    requests = parse_qualtrics_export(str(_qualtrics(tmp_path)))
    assert requests[0].submitted_at == at(14, 0)


def test_dedupe_keeps_latest_per_person_and_ce_type(tmp_path: Path) -> None:
    requests = dedupe_requests(parse_qualtrics_export(str(_qualtrics(tmp_path))))
    kept = sorted((r.name_on_certificate, str(r.ce_type), r.license_number) for r in requests)
    assert kept == [
        # same name + CE type: the 14:00 submission wins even though it is row 1
        ("Ann Lee", NY, "LATEST-111"),
        # same email + CE type: the 13:10 submission wins over 13:05
        ("Ann M. Lee", APA, None),
        # same normalized name (one row has no email)
        ("Bo Diaz", APA, None),
    ]


def test_pipeline_generates_one_certificate_per_person_and_type(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    zoom = write_zoom(
        tmp_path / "zoom.xlsx",
        [
            seg("Ann Lee", "ann@example.test", at(9, 0), at(12, 0)),
            seg("Bo Diaz", "bo@example.test", at(9, 0), at(12, 0)),
        ],
    )
    monkeypatch.setattr(
        pipeline, "generate_all", lambda outputs, _d, **_k: [f"{i}.pdf" for i in range(len(outputs))]
    )
    result = run_pipeline(
        str(zoom), str(_qualtrics(tmp_path)), "T", date(2026, 11, 2), "P", 3, ["APA", "NY"],
        time(9, 0), time(12, 0), output_dir=str(tmp_path / "out"),
        overrides={"Ann M. Lee": "Ann Lee"},
    )
    assert result.total_requests == 3
    certs = sorted((c.full_name, str(c.ce_type), c.license_number) for c in result.eligible)
    assert certs == [
        ("Ann Lee", NY, "LATEST-111"),
        ("Ann M. Lee", APA, None),
        ("Bo Diaz", APA, None),
    ]
