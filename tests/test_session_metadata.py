"""Tests for session save/load of multi-day and delivery metadata."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from src.backends.main import _SessionRequest, create_session, list_sessions
from src.models.training import TrainingConfigError, TrainingMetadata


def test_training_metadata_round_trips_new_fields() -> None:
    meta = TrainingMetadata.from_config(
        {
            "title": "Ethics",
            "date": "2026-03-18",
            "end_date": "2026-03-20",
            "instructor_name": "Dr. Jane Smith",
            "ce_credits": 3,
            "ce_types_offered": ["APA", "NY"],
            "session_start": "09:00",
            "session_end": "12:00",
            "is_virtual": False,
            "location": "Rutgers University in Piscataway, NJ",
        }
    )
    assert meta.is_multi_day is True
    assert meta.end_date is not None
    assert meta.is_virtual is False
    assert meta.location is not None


def test_training_metadata_requires_location_for_in_person() -> None:
    with pytest.raises(TrainingConfigError):
        _ = TrainingMetadata.from_config(
            {
                "title": "Ethics",
                "date": "2026-03-20",
                "instructor_name": "Dr. Jane Smith",
                "ce_credits": 3,
                "ce_types_offered": ["APA"],
                "session_start": "09:00",
                "session_end": "12:00",
                "is_virtual": False,
                "location": None,
            }
        )


def test_session_create_and_list_persist_delivery_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("src.backends.main.SESSIONS_DIR", tmp_path)
    request = _SessionRequest(
        title="Multi Day Ethics",
        date="2026-03-18",
        end_date="2026-03-20",
        is_multi_day=True,
        instructor="Dr. Jane Smith",
        ce_credits=3,
        ce_types="APA,NASP",
        start_time="09:00",
        end_time="12:00",
        is_virtual=False,
        location="Rutgers University in Piscataway, NJ",
    )
    created = asyncio.run(create_session(request))
    assert Path(created["path"]).is_file()

    sessions = asyncio.run(list_sessions())
    assert len(sessions) == 1
    saved = sessions[0]
    assert saved["is_multi_day"] is True
    assert saved["end_date"] == "2026-03-20"
    assert saved["is_virtual"] is False
    assert saved["location"] == "Rutgers University in Piscataway, NJ"
    assert isinstance(saved["id"], str)
    assert saved["id"] == Path(created["path"]).stem
    assert saved["id"] != 0
    assert Path(created["path"]).name != "multi_day_ethics.json"


def test_prune_sessions_removes_old_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("src.backends.main.SESSIONS_DIR", tmp_path)
    request = _SessionRequest(
        title="Old Session",
        date="2026-01-01",
        instructor="Dr. Test",
        ce_credits=3,
        ce_types="APA",
        start_time="09:00",
        end_time="12:00",
    )
    created = asyncio.run(create_session(request))
    session_file = Path(created["path"])
    assert session_file.is_file()

    # Backdate mtime to 31 days ago
    old_time = (datetime.now(tz=UTC) - timedelta(days=31)).timestamp()
    os.utime(session_file, (old_time, old_time))

    sessions = asyncio.run(list_sessions())
    assert len(sessions) == 0
    assert not session_file.exists()


def test_prune_sessions_keeps_recent_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("src.backends.main.SESSIONS_DIR", tmp_path)
    request = _SessionRequest(
        title="Recent Session",
        date="2026-01-01",
        instructor="Dr. Test",
        ce_credits=3,
        ce_types="APA",
        start_time="09:00",
        end_time="12:00",
    )
    created = asyncio.run(create_session(request))
    session_file = Path(created["path"])

    # Create an old session in the same dir
    old_request = _SessionRequest(
        title="Old Session",
        date="2026-01-01",
        instructor="Dr. Test",
        ce_credits=3,
        ce_types="APA",
        start_time="09:00",
        end_time="12:00",
    )
    old_created = asyncio.run(create_session(old_request))
    old_file = Path(old_created["path"])
    old_time = (datetime.now(tz=UTC) - timedelta(days=31)).timestamp()
    os.utime(old_file, (old_time, old_time))

    sessions = asyncio.run(list_sessions())
    assert len(sessions) == 1
    assert sessions[0]["title"] == "Recent Session"
    assert not old_file.exists()
    assert session_file.is_file()
