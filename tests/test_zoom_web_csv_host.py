"""Zoom web CSV exports name the host only by "User Email" (synthetic data).

Assumption: in the web portal's participant CSV (Reports > Usage), the
meeting block's "User Email" column is the meeting host's account email.
"""

from __future__ import annotations

import csv
from typing import TYPE_CHECKING

from src.parser.zoom import parse_zoom_attendance

if TYPE_CHECKING:
    from pathlib import Path


def _write_web_csv(path: Path, *, host_email: str) -> Path:
    rows = [
        [
            "Meeting ID",
            "Topic",
            "Start Time",
            "End Time",
            "User Email",
            "Duration (Minutes)",
            "Participants",
        ],
        [
            "999 0001 1122",
            "Synthetic CE Workshop",
            "11/02/2026 08:30:00 AM",
            "11/02/2026 12:15:00 PM",
            host_email,
            "225",
            "2",
        ],
        [],
        [
            "Name (Original Name)",
            "User Email",
            "Join Time",
            "Leave Time",
            "Duration (Minutes)",
            "Guest",
            "In Waiting Room",
        ],
        [
            "Hana Host",
            "hana.host@example.test",
            "11/02/2026 08:30:00 AM",
            "11/02/2026 12:15:00 PM",
            "225",
            "No",
            "No",
        ],
        [
            "Olive Ontime",
            "olive@example.test",
            "11/02/2026 08:58:00 AM",
            "11/02/2026 12:01:00 PM",
            "183",
            "No",
            "No",
        ],
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        csv.writer(handle).writerows(rows)
    return path


def test_host_is_found_from_user_email(tmp_path: Path) -> None:
    session = parse_zoom_attendance(
        str(_write_web_csv(tmp_path / "web.csv", host_email="hana.host@example.test"))
    )
    assert session.host == "Hana Host"


def test_host_email_matching_is_case_insensitive(tmp_path: Path) -> None:
    session = parse_zoom_attendance(
        str(_write_web_csv(tmp_path / "web.csv", host_email="Hana.Host@Example.test"))
    )
    assert session.host == "Hana Host"


def test_unknown_host_email_leaves_host_unset(tmp_path: Path) -> None:
    session = parse_zoom_attendance(
        str(_write_web_csv(tmp_path / "web.csv", host_email="someone.else@example.test"))
    )
    assert session.host is None
