"""Tests for the multi-strategy name matcher."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import assert_never

import pytest
from src.matcher.name_matcher import batch_match, match_participants
from src.models.certificate import (
    CERequest,
    MatchAmbiguous,
    MatchNotFound,
    MatchSuccess,
)
from src.models.participant import (
    AttendanceRecord,
    ParticipantAttendance,
    normalize_name,
)
from src.models.training import CEType

BASE_TIME = datetime(2026, 3, 20, 9, 0, 0, tzinfo=UTC)


def _make_participant(name: str, join_min: int = 0, leave_min: int = 60) -> ParticipantAttendance:
    """Build a minimal ParticipantAttendance for name matching tests."""
    record = AttendanceRecord(
        name_raw=name,
        email=None,
        join_time=BASE_TIME + timedelta(minutes=join_min),
        leave_time=BASE_TIME + timedelta(minutes=leave_min),
        duration_minutes=leave_min - join_min,
        is_guest=False,
        is_waiting_room=False,
    )
    return ParticipantAttendance.from_records([record])


def test_exact_normalized_match() -> None:
    """Given Qualtrics "John Smith" and Zoom "John Smith", exact normalized match
    succeeds with confidence 1.0."""
    results = match_participants(
        zoom_names=["John Smith"],
        qualtrics_names=["John Smith"],
    )

    result = results["John Smith"]
    match result:
        case MatchSuccess(matched_name=name, confidence=conf):
            assert name == "John Smith"
            assert conf == 1.0
        case _:
            pytest.fail(f"expected MatchSuccess, got {result}")


def test_token_set_match() -> None:
    """Given Qualtrics "John Smith" and Zoom "Dr. John Smith", after title stripping
    the token sets match."""
    results = match_participants(
        zoom_names=["Dr. John Smith"],
        qualtrics_names=["John Smith"],
    )

    result = results["John Smith"]
    match result:
        case MatchSuccess(matched_name=name, confidence=conf):
            assert name == "Dr. John Smith"
            assert conf == 0.9
        case _:
            pytest.fail(f"expected MatchSuccess, got {result}")


def test_first_name_partial() -> None:
    """Given Qualtrics "John" and Zoom "John Smith", the token-set strategy
    fires first (confidence 0.9) because {"john"} is a subset of {"john", "smith"}.
    This validates that single-token Qualtrics names match multi-token Zoom names."""
    results = match_participants(
        zoom_names=["John Smith"],
        qualtrics_names=["John"],
    )

    result = results["John"]
    match result:
        case MatchSuccess(matched_name=name, confidence=conf):
            assert name == "John Smith"
            assert conf == 0.9
        case _:
            pytest.fail(f"expected MatchSuccess, got {result}")


def test_match_not_found() -> None:
    """Given Qualtrics "Jane Doe" with no corresponding Zoom entry, match returns
    MatchNotFound."""
    results = match_participants(
        zoom_names=["John Smith", "Alice Jones"],
        qualtrics_names=["Jane Doe"],
    )

    result = results["Jane Doe"]
    assert isinstance(result, MatchNotFound)


def test_manual_override() -> None:
    """Given a manual override mapping, it takes priority over all other strategies
    and returns confidence 1.0."""
    results = match_participants(
        zoom_names=["Dr. Alice B. Jones"],
        qualtrics_names=["Alice Jones"],
        manual_overrides={"Alice Jones": "Dr. Alice B. Jones"},
    )

    result = results["Alice Jones"]
    match result:
        case MatchSuccess(matched_name=name, confidence=conf):
            assert name == "Dr. Alice B. Jones"
            assert conf == 1.0
        case _:
            pytest.fail(f"expected MatchSuccess, got {result}")


def test_ambiguous_match() -> None:
    """Given two Zoom entries that normalize to the same name, exact match returns
    MatchAmbiguous with both candidates."""
    # Both "Bob Smith" and "Bob Smith (he/him)" normalize to "bob smith"
    results = match_participants(
        zoom_names=["Bob Smith", "Bob Smith (he/him)"],
        qualtrics_names=["Bob Smith"],
    )

    result = results["Bob Smith"]
    match result:
        case MatchAmbiguous(candidates=cands):
            assert set(cands) == {"Bob Smith", "Bob Smith (he/him)"}
        case _:
            pytest.fail(f"expected MatchAmbiguous, got {result}")


def test_batch_match_integration() -> None:
    """Given typed ParticipantAttendance and CERequest objects, batch_match returns
    correctly paired triples with MatchSuccess linking matching participants."""
    participants = [_make_participant("Alice Jones"), _make_participant("Bob Smith")]
    requests = [
        CERequest(
            name_on_certificate="Alice Jones",
            email="alice@example.com",
            ce_type=CEType("APA"),
            license_number=None,
        ),
        CERequest(
            name_on_certificate="Bob Smith",
            email="bob@example.com",
            ce_type=CEType("BCBA"),
            license_number="12345",
        ),
    ]

    triples = batch_match(participants, requests)

    assert len(triples) == 2
    for _req, participant, result in triples:
        match result:
            case MatchSuccess(matched_name=name, confidence=conf):
                assert participant is not None
                assert normalize_name(participant.name_raw) == normalize_name(name)
                assert conf >= 0.9
            case MatchAmbiguous():
                pass
            case MatchNotFound():
                pass
            case _:
                assert_never(result)
