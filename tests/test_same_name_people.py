"""Different people who share a name or an email must each be judged on their own.

Code review repros (H1):
(a) Pat Kim and Lee Kim share a family email and both attended.
(b) Two Chris Parks with different emails ask for the same CE type; only one
    stayed for the whole session.
(c) The same two Chris Parks ask for different CE types; only one joined.
Dropped duplicate rows must also show up in the report.
"""

from __future__ import annotations

import asyncio
from datetime import date, time
from typing import TYPE_CHECKING

import src.pipeline as pipeline
from src.backends.routes import MatchRequest, match_endpoint
from src.models.certificate import EligibilityStatus
from src.parser.qualtrics import parse_qualtrics_export
from src.pipeline import PipelineResult, dedupe_requests, run_pipeline

from tests.synthetic import at, seg, write_qualtrics, write_zoom

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

APA = "Psychologist (APA)"
NBCC = "Counselor (NBCC)"
HOST = seg("Hana Host", "hana.host@example.test", at(8, 30), at(12, 15))


def _run(tmp_path: Path, zoom: Path, qualtrics: Path, monkeypatch: pytest.MonkeyPatch) -> PipelineResult:
    monkeypatch.setattr(
        pipeline, "generate_all", lambda outputs, _d, **_k: [f"{i}.pdf" for i in range(len(outputs))]
    )
    return run_pipeline(
        str(zoom), str(qualtrics), "T", date(2026, 11, 2), "P", 3, ["APA", "NBCC"],
        time(9, 0), time(12, 0), output_dir=str(tmp_path / "out"),
    )


def _certs(result: PipelineResult) -> list[tuple[str, str]]:
    return sorted((c.full_name, str(c.ce_type)) for c in result.eligible)


def test_shared_email_with_different_names_is_not_a_duplicate(tmp_path: Path) -> None:
    q = write_qualtrics(
        tmp_path / "q.xlsx",
        [("Pat Kim", "family@example.test", APA, None), ("Lee Kim", "family@example.test", APA, None)],
    )
    kept = dedupe_requests(parse_qualtrics_export(str(q)))
    assert sorted(r.name_on_certificate for r in kept) == ["Lee Kim", "Pat Kim"]


def test_same_name_with_different_emails_is_not_a_duplicate(tmp_path: Path) -> None:
    q = write_qualtrics(
        tmp_path / "q.xlsx",
        [("Chris Park", "chris.p1@example.test", APA, None), ("Chris Park", "chris.p2@example.test", APA, None)],
    )
    kept = dedupe_requests(parse_qualtrics_export(str(q)))
    assert sorted(r.email or "" for r in kept) == ["chris.p1@example.test", "chris.p2@example.test"]


def test_a_shared_family_email_certifies_both_people(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    zoom = write_zoom(
        tmp_path / "z.xlsx",
        [
            HOST,
            seg("Pat Kim", "family@example.test", at(9, 0), at(12, 0)),
            seg("Lee Kim", "family@example.test", at(9, 0), at(12, 0)),
        ],
        meeting_start=at(8, 30),
        meeting_end=at(12, 15),
    )
    q = write_qualtrics(
        tmp_path / "q.xlsx",
        [("Pat Kim", "family@example.test", APA, None), ("Lee Kim", "family@example.test", APA, None)],
    )
    result = _run(tmp_path, zoom, q, monkeypatch)
    assert _certs(result) == [("Lee Kim", APA), ("Pat Kim", APA)]
    assert result.total_requests == 2


def test_two_people_named_alike_are_judged_on_their_own_attendance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    zoom = write_zoom(
        tmp_path / "z.xlsx",
        [
            HOST,
            seg("Chris Park", "chris.p1@example.test", at(9, 0), at(12, 0)),
            seg("Chris Park", "chris.p2@example.test", at(9, 0), at(9, 20)),
        ],
        meeting_start=at(8, 30),
        meeting_end=at(12, 15),
    )
    # The one who left at 9:20 submitted last.
    q = write_qualtrics(
        tmp_path / "q.xlsx",
        [("Chris Park", "chris.p1@example.test", APA, None), ("Chris Park", "chris.p2@example.test", APA, None)],
        recorded=[at(12, 5), at(12, 30)],
    )
    result = _run(tmp_path, zoom, q, monkeypatch)
    assert _certs(result) == [("Chris Park", APA)]
    assert len(result.ineligible) == 1
    entry = result.ineligible[0]
    assert entry.status == EligibilityStatus.ATTENDANCE_INSUFFICIENT
    assert "chris.p2@example.test" in (entry.name_zoom or "")


def test_same_name_different_ce_type_does_not_borrow_attendance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    zoom = write_zoom(
        tmp_path / "z.xlsx",
        [HOST, seg("Chris Park", "chris.p1@example.test", at(9, 0), at(12, 0))],
        meeting_start=at(8, 30),
        meeting_end=at(12, 15),
    )
    q = write_qualtrics(
        tmp_path / "q.xlsx",
        [("Chris Park", "chris.p1@example.test", APA, None), ("Chris Park", "chris.p2@example.test", NBCC, None)],
    )
    result = _run(tmp_path, zoom, q, monkeypatch)
    assert _certs(result) == [("Chris Park", APA)]
    assert [(e.name_qualtrics, e.rejected_ce_types) for e in result.ineligible] == [
        ("Chris Park", (NBCC,)),
    ]


def test_one_person_asking_for_two_ce_types_gets_both(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    zoom = write_zoom(
        tmp_path / "z.xlsx",
        [HOST, seg("Dana Ruiz", "dana@example.test", at(9, 0), at(12, 0))],
        meeting_start=at(8, 30),
        meeting_end=at(12, 15),
    )
    q = write_qualtrics(
        tmp_path / "q.xlsx",
        [("Dana Ruiz", "dana@example.test", APA, None), ("Dana Ruiz", "dana@example.test", NBCC, None)],
    )
    result = _run(tmp_path, zoom, q, monkeypatch)
    assert _certs(result) == [("Dana Ruiz", NBCC), ("Dana Ruiz", APA)]


def test_dropped_duplicates_are_listed_in_the_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    zoom = write_zoom(
        tmp_path / "z.xlsx",
        [HOST, seg("Alice Anders", "alice@example.test", at(9, 0), at(12, 0))],
        meeting_start=at(8, 30),
        meeting_end=at(12, 15),
    )
    q = write_qualtrics(
        tmp_path / "q.xlsx",
        [("Alice Anders", "alice@example.test", APA, None), ("Alice Anders", "alice@example.test", APA, None)],
    )
    result = _run(tmp_path, zoom, q, monkeypatch)
    assert _certs(result) == [("Alice Anders", APA)]
    assert [(e.name_qualtrics, e.status) for e in result.ineligible] == [
        ("Alice Anders", EligibilityStatus.DUPLICATE_SUBMISSION),
    ]
    assert "Duplicate submission" in result.ineligible[0].reason
    assert result.total_requests == 2


def test_match_endpoint_returns_one_entry_per_person(tmp_path: Path) -> None:
    zoom = write_zoom(
        tmp_path / "z.xlsx",
        [
            HOST,
            seg("Chris Park", "chris.p1@example.test", at(9, 0), at(12, 0)),
            seg("Chris Park", "chris.p2@example.test", at(9, 0), at(9, 20)),
        ],
        meeting_start=at(8, 30),
        meeting_end=at(12, 15),
    )
    body = MatchRequest.model_validate(
        {
            "zoom_participants": [],
            "ce_requests": [
                {"name_on_certificate": "Chris Park", "ce_type": APA, "email": "chris.p1@example.test"},
                {"name_on_certificate": "Chris Park", "ce_type": APA, "email": "chris.p2@example.test"},
            ],
            "zoom_path": str(zoom),
            "start_time": "09:00",
            "end_time": "12:00",
        }
    )
    response = asyncio.run(match_endpoint(body))
    entries = [
        (m.request_indices, m.zoom_name, (m.attendance or {}).get("is_eligible"))
        for m in response.matches
    ]
    assert entries == [
        ([0], "Chris Park (chris.p1@example.test)", True),
        ([1], "Chris Park (chris.p2@example.test)", False),
    ]
