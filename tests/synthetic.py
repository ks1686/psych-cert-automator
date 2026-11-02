"""Synthetic Zoom and Qualtrics workbooks for regression tests.

Every person, email, and meeting ID here is made up. Tests that need their
own inputs build them with these helpers instead of editing the shared
fixtures.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import openpyxl

if TYPE_CHECKING:
    from pathlib import Path

CE_QUESTION = (
    "Type of CE credit needed:\n\n\n(please note that the below options represent "
    "available CEs across all GSAPP offerings.)"
)
NAME_HEADER = "Name (as you would like it to appear on your CE certificate):"
EMAIL_HEADER = "Preferred email address:"
SELECTED_HEADER = f"{CE_QUESTION} - Selected Choice"
NY_LICENSE_HEADER = (
    f"{CE_QUESTION} - Psychologist (New York) (please enter your NY license #) - Text"
)

ZoomRow = tuple[str, str | None, datetime, datetime, str]
"""(name, email, join, leave, waiting_room 'Yes'/'No')."""


def at(hour: int, minute: int, day: int = 2) -> datetime:
    """Return a datetime on the synthetic meeting day (Nov 2026)."""
    return datetime(2026, 11, day, hour, minute)


def seg(
    name: str,
    email: str | None,
    join: datetime,
    leave: datetime,
    *,
    waiting_room: bool = False,
) -> ZoomRow:
    """Build one Zoom segment row."""
    return (name, email, join, leave, "Yes" if waiting_room else "No")


def write_zoom(
    path: Path,
    rows: list[ZoomRow],
    *,
    meeting_start: datetime | None = None,
    meeting_end: datetime | None = None,
    extra_top_row: bool = False,
) -> Path:
    """Write a Zoom usage-report workbook with the standard 4-row header."""
    wb = openpyxl.Workbook()
    ws = wb.active
    assert ws is not None
    if extra_top_row:
        ws.append(["Zoom attendance report"])
    ws.append(["Topic", "ID", "Host", "Duration (minutes)", "Start time", "End time", "Participants"])
    ws.append(
        [
            "Synthetic CE Workshop",
            99900011122,
            "Hana Host (hana.host@example.test)",
            180,
            meeting_start or at(9, 0),
            meeting_end or at(12, 0),
            len(rows),
        ]
    )
    ws.append([None] * 7)
    ws.append(
        [
            "Name (original name)",
            "Email",
            "Join time",
            "Leave time",
            "Duration (minutes)",
            "Guest",
            "In waiting room",
        ]
    )
    for name, email, join, leave, waiting in rows:
        minutes = int((leave - join).total_seconds() // 60)
        ws.append([name, email, join, leave, minutes, "No", waiting])
    wb.save(path)
    return path


QualtricsRow = tuple[str, str | None, str, str | None]
"""(name, email, CE selection, NY license)."""


def write_qualtrics(
    path: Path,
    rows: list[QualtricsRow],
    *,
    three_header: bool = False,
    finished: list[bool] | None = None,
    recorded: list[datetime] | None = None,
) -> Path:
    """Write a Qualtrics export (1 label row, or the 3-row API export)."""
    labels = [
        "Start Date",
        "End Date",
        "Response Type",
        "Progress",
        "Finished",
        "Recorded Date",
        "Response ID",
        NAME_HEADER,
        EMAIL_HEADER,
        SELECTED_HEADER,
        NY_LICENSE_HEADER,
    ]
    wb = openpyxl.Workbook()
    ws = wb.active
    assert ws is not None
    if three_header:
        ws.append(
            [
                "StartDate",
                "EndDate",
                "Status",
                "Progress",
                "Finished",
                "RecordedDate",
                "ResponseId",
                "Q1",
                "Q2",
                "Q3",
                "Q3_2_TEXT",
            ]
        )
        ws.append(labels)
        ws.append([f'{{"ImportId":"QID{i}"}}' for i in range(len(labels))])
    else:
        ws.append(labels)
    for i, (name, email, ce, lic) in enumerate(rows):
        done = True if finished is None else finished[i]
        when = recorded[i] if recorded is not None else at(13, i % 60)
        ws.append(
            [
                None,
                None,
                "IP Address",
                100 if done else 40,
                "True" if done else "False",
                when,
                f"R_SYNTHETIC{i:04d}",
                name,
                email,
                ce,
                lic,
            ]
        )
    wb.save(path)
    return path


def write_zoom_csv(
    path: Path,
    rows: list[ZoomRow],
    *,
    meeting_start: datetime | None = None,
    meeting_end: datetime | None = None,
) -> Path:
    """Write a Zoom web-portal CSV export (UTF-8 with BOM, 12-hour times)."""
    fmt = "%m/%d/%Y %I:%M:%S %p"
    start = meeting_start or at(9, 0)
    end = meeting_end or at(12, 0)
    lines = [
        "Meeting ID,Topic,Start Time,End Time,User Email,Duration (Minutes),Participants",
        f"999 0001 1122,Synthetic CE Workshop,{start.strftime(fmt)},{end.strftime(fmt)},"
        f"hana.host@example.test,180,{len(rows)}",
        "",
        "Name (Original Name),User Email,Join Time,Leave Time,Duration (Minutes),Guest,"
        "In Waiting Room",
    ]
    for name, email, join, leave, waiting in rows:
        minutes = int((leave - join).total_seconds() // 60)
        lines.append(
            f"{name},{email or ''},{join.strftime(fmt)},{leave.strftime(fmt)},{minutes},No,{waiting}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
    return path


def write_qualtrics_csv(path: Path, rows: list[QualtricsRow]) -> Path:
    """Write a Qualtrics CSV export with the 3 header rows Qualtrics uses."""
    import csv  # noqa: PLC0415

    xlsx = write_qualtrics(path.with_suffix(".tmp.xlsx"), rows, three_header=True)
    wb = openpyxl.load_workbook(xlsx)
    ws = wb.active
    assert ws is not None
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        for row in ws.iter_rows(values_only=True):
            writer.writerow(
                ["" if v is None else (v.strftime("%Y-%m-%d %H:%M:%S") if isinstance(v, datetime) else v) for v in row]
            )
    xlsx.unlink()
    return path
