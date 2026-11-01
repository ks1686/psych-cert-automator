"""Fuzzy name matches must never hand a certificate to a non-attendee."""

from __future__ import annotations

from datetime import date, time
from typing import TYPE_CHECKING

import pytest
from src import pipeline
from src.matcher.name_matcher import match_participants
from src.models.certificate import EligibilityStatus, MatchNotFound, MatchSuccess
from src.models.participant import normalize_name
from src.pipeline import run_pipeline

from tests.synthetic import at, seg, write_qualtrics, write_zoom

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Li Ma", "li ma"),
        ("Rosa Pa", "rosa pa"),
        ("Ana Np", "ana np"),
        ("Joy Rn", "joy rn"),
        ("Eli Ms", "eli ms"),
        ("Kai Jd", "kai jd"),
        ("Pat Smith, MA", "pat smith"),
        ("Pat Smith, M.A., LPC", "pat smith"),
        ("Pat Smith MA", "pat smith"),
        ("Pat Smith PhD", "pat smith"),
        ("Dr. Gina Gold (she/her)", "gina gold"),
        ("Jaimee Arnoff# Ph.D. (she/her)", "jaimee arnoff"),
    ],
)
def test_credentials_never_eat_a_surname(raw: str, expected: str) -> None:
    assert normalize_name(raw) == expected


def test_li_ma_does_not_match_li_wong() -> None:
    result = match_participants(["Li Wong"], ["Li Ma"])
    assert isinstance(result["Li Ma"], MatchNotFound)


def test_sam_rivera_against_bare_sam_needs_review() -> None:
    result = match_participants(["Sam"], ["Sam Rivera"])["Sam Rivera"]
    assert isinstance(result, MatchSuccess)
    assert result.confidence < 1.0


def test_email_breaks_a_tie_between_same_named_attendees() -> None:
    result = match_participants(
        ["Chris Park (chris.p1@example.test)", "Chris Park (chris.p2@example.test)"],
        ["Chris Park"],
        zoom_emails={
            "Chris Park (chris.p1@example.test)": "chris.p1@example.test",
            "Chris Park (chris.p2@example.test)": "Chris.P2@Example.test",
        },
        qualtrics_emails={"Chris Park": "chris.p2@example.test"},
    )["Chris Park"]
    assert result == MatchSuccess(
        matched_name="Chris Park (chris.p2@example.test)", confidence=1.0
    )


def test_matching_email_confirms_a_partial_name_match() -> None:
    result = match_participants(
        ["Maria Garcia Lopez"],
        ["Maria Garcia"],
        zoom_emails={"Maria Garcia Lopez": "maria@example.test"},
        qualtrics_emails={"Maria Garcia": "MARIA@example.test"},
    )["Maria Garcia"]
    assert result == MatchSuccess(matched_name="Maria Garcia Lopez", confidence=1.0)


def test_pipeline_issues_no_certificate_for_fuzzy_matches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    zoom = write_zoom(
        tmp_path / "zoom.xlsx",
        [
            seg("Li Wong", "liwong@example.test", at(9, 0), at(12, 0)),
            seg("Sam", "sam.other@example.test", at(9, 0), at(12, 0)),
            seg("Alice Anders", "alice@example.test", at(9, 0), at(12, 0)),
        ],
    )
    qualtrics = write_qualtrics(
        tmp_path / "q.xlsx",
        [
            ("Li Ma", "lima@example.test", "Psychologist (APA)", None),
            ("Sam Rivera", "sam.rivera@example.test", "Psychologist (APA)", None),
            ("Alice Anders", "alice@example.test", "Psychologist (APA)", None),
        ],
    )
    monkeypatch.setattr(
        pipeline, "generate_all", lambda outputs, _d, **_k: [f"{i}.pdf" for i in range(len(outputs))]
    )
    result = run_pipeline(
        str(zoom), str(qualtrics), "T", date(2026, 11, 2), "P", 3, ["APA"],
        time(9, 0), time(12, 0), output_dir=str(tmp_path / "out"),
    )
    assert [c.full_name for c in result.eligible] == ["Alice Anders"]
    status = {e.name_qualtrics: e.status for e in result.ineligible}
    assert status["Li Ma"] is EligibilityStatus.NOT_FOUND_IN_ATTENDANCE
    assert status["Sam Rivera"] is EligibilityStatus.NEEDS_REVIEW

    # An explicit include (override) is what lets a fuzzy match through.
    approved = run_pipeline(
        str(zoom), str(qualtrics), "T", date(2026, 11, 2), "P", 3, ["APA"],
        time(9, 0), time(12, 0), output_dir=str(tmp_path / "out"),
        overrides={"Sam Rivera": "Sam"},
    )
    assert sorted(c.full_name for c in approved.eligible) == ["Alice Anders", "Sam Rivera"]
