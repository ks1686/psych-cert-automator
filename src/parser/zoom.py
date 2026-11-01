"""Zoom attendance report parser — reads .xlsx into typed participant data.

Parses a Zoom "Usage Report" attendance .xlsx export, extracts session
metadata, filters out waiting-room segments, groups records by normalized
participant name, and returns one ``ParticipantAttendance`` per unique person.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime
from typing import TYPE_CHECKING, override

from src.models.participant import (
    AttendanceRecord,
    ParticipantAttendance,
    ParticipantDataError,
    normalize_name,
)
from src.parser.tabular import UnreadableFileError, read_rows

if TYPE_CHECKING:
    from collections.abc import Callable


@dataclass(frozen=True, slots=True)
class ZoomSession:
    """Container for a parsed Zoom attendance report.

    Attributes:
        session_start: When the Zoom meeting started.
        session_end: When the Zoom meeting ended.
        participants: One ``ParticipantAttendance`` per unique person,
            sorted by ``first_join`` ascending.
    """

    session_start: datetime
    session_end: datetime
    participants: tuple[ParticipantAttendance, ...]
    host: str | None = None
    """Meeting host display name (email parenthetical removed), if listed."""


@dataclass(frozen=True, slots=True)
class ZoomParseError(Exception):
    """Error raised when a Zoom attendance report cannot be parsed.

    Carries the filepath and a human-readable reason so callers can surface
    precise diagnostics.
    """

    filepath: str
    reason: str

    @override
    def __str__(self) -> str:
        """Return a human-readable error message."""
        return f"Zoom parse error for {self.filepath!r}: {self.reason}"


def parse_zoom_attendance(filepath: str) -> ZoomSession:
    """Parse a Zoom attendance report (.xlsx or .csv) into typed participant data.

    The participant header row is found by keyword ("Join time"), so an extra
    title row above the report, or the Zoom web CSV layout, still parses.
    Meeting start/end (and host, when present) come from the metadata block
    above it. Waiting-room segments are dropped, records are grouped by
    normalized name and, when people share a name, by email.

    Args:
        filepath: Path to the Zoom attendance report.

    Returns:
        A ``ZoomSession`` containing session times and one
        ``ParticipantAttendance`` per unique person.

    Raises:
        ZoomParseError: If the file is missing, unreadable, or contains
            unparseable data.
    """
    try:
        rows = read_rows(filepath)
    except FileNotFoundError:
        raise ZoomParseError(filepath=filepath, reason="file not found") from None
    except UnreadableFileError as exc:
        raise ZoomParseError(filepath=filepath, reason=str(exc)) from exc

    header_idx = _find_header_row(rows)
    if header_idx is None:
        raise ZoomParseError(
            filepath=filepath,
            reason="could not find the participant header row (with a 'Join time' column)",
        )
    columns = _participant_columns(rows[header_idx])
    if columns is None:
        raise ZoomParseError(
            filepath=filepath,
            reason="participant header row needs Name, Join time, and Leave time columns",
        )
    session_start, session_end, host, host_email = _session_metadata(
        rows[:header_idx], filepath,
    )

    raw_records = [
        _parse_attendance_row(_pick(row, columns), filepath)
        for row in rows[header_idx + 1 :]
        if row and _cell(row, columns[0]) is not None
    ]

    # Filter out waiting-room segments, then group by person.
    active = [r for r in raw_records if not r.is_waiting_room]

    participants: list[ParticipantAttendance] = []
    for label, group in _group_people(active):
        try:
            person = ParticipantAttendance.from_records(group)
        except ParticipantDataError:
            # Should not happen after filtering, but skip gracefully.
            continue
        participants.append(replace(person, name_raw=label))

    participants.sort(key=lambda p: p.first_join)

    if host is None and host_email:
        host = _host_by_email(active, host_email)

    return ZoomSession(
        session_start=session_start,
        session_end=session_end,
        participants=tuple(participants),
        host=host,
    )


# ── Internal helpers ──────────────────────────────────────────────────────────

_ColumnMap = tuple[int, int | None, int, int, int | None, int | None, int | None]
"""Indices of name, email, join, leave, duration, guest, waiting room."""

_HEADER_SCAN_ROWS = 20
_EMAIL_IN_PARENS = re.compile(r"\s*\([^)]*@[^)]*\)\s*$")
_DATETIME_FORMATS = (
    "%m/%d/%Y %I:%M:%S %p",
    "%m/%d/%Y %I:%M %p",
    "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y %H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
)


def _text(value: object) -> str:
    return str(value).strip().lower() if value is not None else ""


def _cell(row: tuple[object, ...], idx: int | None) -> object:
    if idx is None or idx >= len(row):
        return None
    return row[idx]


def _find_header_row(rows: list[tuple[object, ...]]) -> int | None:
    for i, row in enumerate(rows[:_HEADER_SCAN_ROWS]):
        if any(_text(cell).startswith("join time") for cell in row):
            return i
    return None


def _participant_columns(header: tuple[object, ...]) -> _ColumnMap | None:
    labels = [_text(cell) for cell in header]

    def find(test: Callable[[str], bool]) -> int | None:
        return next((i for i, label in enumerate(labels) if test(label)), None)

    name = find(lambda t: t.startswith("name"))
    join = find(lambda t: t.startswith("join time"))
    leave = find(lambda t: t.startswith("leave time"))
    if name is None or join is None or leave is None:
        return None
    return (
        name,
        find(lambda t: "email" in t),
        join,
        leave,
        find(lambda t: t.startswith("duration")),
        find(lambda t: t == "guest"),
        find(lambda t: "waiting room" in t),
    )


def _pick(row: tuple[object, ...], columns: _ColumnMap) -> tuple[object, ...]:
    """Reorder a data row into the canonical 7-column layout."""
    name, email, join, leave, duration, guest, waiting = columns
    return (
        _cell(row, name),
        _cell(row, email),
        _cell(row, join),
        _cell(row, leave),
        _cell(row, duration),
        _cell(row, guest) if guest is not None else "No",
        _cell(row, waiting) if waiting is not None else "No",
    )


def _host_by_email(records: list[AttendanceRecord], host_email: str) -> str | None:
    """Display name of the attendee whose email is the host's, if any."""
    wanted = host_email.strip().casefold()
    for record in records:
        if (record.email or "").strip().casefold() == wanted:
            return _EMAIL_IN_PARENS.sub("", record.name_raw).strip() or record.name_raw
    return None


def _session_metadata(
    rows: list[tuple[object, ...]],
    filepath: str,
) -> tuple[datetime, datetime, str | None, str | None]:
    """Find meeting start, end, host, and host email above the participants.

    The desktop/usage report has a "Host" column. The Zoom web portal CSV has
    no host name, only "User Email", which is assumed to be the host's
    account email; the caller turns it into a name using the attendee list.
    """
    for i, row in enumerate(rows[:-1]):
        labels = [_text(cell) for cell in row]
        if "start time" in labels and "end time" in labels:
            values = rows[i + 1]
            start = _parse_datetime_cell(
                _cell(values, labels.index("start time")), "session_start", filepath,
            )
            end = _parse_datetime_cell(
                _cell(values, labels.index("end time")), "session_end", filepath,
            )
            host_idx = next(
                (j for j, label in enumerate(labels) if label in {"host", "host name"}),
                None,
            )
            host_raw = _cell(values, host_idx)
            host = None
            if isinstance(host_raw, str) and host_raw.strip():
                host = _EMAIL_IN_PARENS.sub("", host_raw).strip() or host_raw.strip()
            email_idx = next(
                (j for j, label in enumerate(labels) if label in {"user email", "host email"}),
                None,
            )
            email_raw = _cell(values, email_idx)
            has_email = isinstance(email_raw, str) and "@" in email_raw
            host_email = email_raw.strip() if has_email else None
            return start, end, host, host_email
    raise ZoomParseError(
        filepath=filepath,
        reason="could not find the meeting Start time / End time above the participant list",
    )


def _group_people(
    records: list[AttendanceRecord],
) -> list[tuple[str, list[AttendanceRecord]]]:
    """Group segments by normalized name, then split a name by distinct emails.

    Segments without an email join the only emailed group for that name;
    if two or more people share the name, they stay in their own group.
    Groups that share a display name are labelled ``"Name (email)"`` so each
    label is unique (the parenthetical is ignored by name matching).
    """
    by_name: dict[str, list[AttendanceRecord]] = {}
    for record in records:
        by_name.setdefault(normalize_name(record.name_raw), []).append(record)

    groups: list[list[AttendanceRecord]] = []
    for same_name in by_name.values():
        by_email: dict[str, list[AttendanceRecord]] = {}
        no_email: list[AttendanceRecord] = []
        for record in same_name:
            key = (record.email or "").strip().casefold()
            if key:
                by_email.setdefault(key, []).append(record)
            else:
                no_email.append(record)
        if len(by_email) <= 1:
            groups.append(same_name)
            continue
        groups.extend(by_email.values())
        if no_email:
            groups.append(no_email)

    first_label: dict[str, int] = {}
    for group in groups:
        name = group[0].name_raw
        first_label[name] = first_label.get(name, 0) + 1

    labelled: list[tuple[str, list[AttendanceRecord]]] = []
    for group in groups:
        name = group[0].name_raw
        email = next((r.email.strip() for r in group if r.email and r.email.strip()), None)
        if first_label[name] > 1 and email:
            labelled.append((f"{name} ({email})", group))
        else:
            labelled.append((name, group))
    return labelled


def _parse_datetime_cell(
    value: object,
    label: str,
    filepath: str,
) -> datetime:
    """Parse a cell value that must be a ``datetime``.

    Args:
        value: Raw cell value from openpyxl.
        label: Human-readable field name for error messages.
        filepath: Source file for error context.

    Returns:
        The parsed ``datetime``.

    Raises:
        ZoomParseError: If the value is not a ``datetime``.
    """
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        text = value.strip()
        for fmt in _DATETIME_FORMATS:
            try:
                return datetime.strptime(text, fmt)  # noqa: DTZ007  # Zoom exports local time
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            pass
    raise ZoomParseError(
        filepath=filepath,
        reason=f"expected datetime for {label}, got {type(value).__name__}: {value!r}",
    )


def _parse_attendance_row(
    row: tuple[object, ...],
    filepath: str,
) -> AttendanceRecord:
    """Parse a single participant data row into an ``AttendanceRecord``.

    Expects a 7-element tuple in Zoom report column order: name, email,
    join_time, leave_time, duration, guest, waiting_room.

    Args:
        row: Raw row tuple from openpyxl ``iter_rows(values_only=True)``.
        filepath: Source file for error context.

    Returns:
        A validated ``AttendanceRecord``.

    Raises:
        ZoomParseError: If any cell contains unparseable data.
    """
    name_raw = _parse_name_cell(row[0], filepath)
    email = _parse_email_cell(row[1])
    join_time = _parse_datetime_cell(row[2], f"join_time for {name_raw!r}", filepath)
    leave_time = _parse_datetime_cell(row[3], f"leave_time for {name_raw!r}", filepath)
    duration = _parse_duration_cell(row[4], name_raw, filepath)
    is_guest = _parse_yes_no(row[5], "guest", name_raw, filepath)
    is_waiting_room = _parse_yes_no(row[6], "waiting room", name_raw, filepath)

    return AttendanceRecord(
        name_raw=name_raw,
        email=email,
        join_time=join_time,
        leave_time=leave_time,
        duration_minutes=duration,
        is_guest=is_guest,
        is_waiting_room=is_waiting_room,
    )


def _parse_name_cell(value: object, filepath: str) -> str:
    """Parse a name cell value — must be a non-empty string.

    Args:
        value: Raw cell value.
        filepath: Source file for error context.

    Returns:
        The name string, with leading/trailing whitespace stripped.

    Raises:
        ZoomParseError: If the value is not a non-empty string.
    """
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise ZoomParseError(
        filepath=filepath,
        reason=f"expected non-empty string for name, got {value!r}",
    )


def _parse_email_cell(value: object) -> str | None:
    """Parse an email cell value — string or None.

    Args:
        value: Raw cell value (may be ``str``, ``None``, or other).

    Returns:
        The email string, or ``None`` if the cell was empty or non-string.
    """
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _parse_duration_cell(
    value: object,
    name: str,
    filepath: str,
) -> int:
    """Parse a duration cell value — must be a non-negative integer.

    Args:
        value: Raw cell value (typically ``int`` from Zoom).
        name: Participant name for error context.
        filepath: Source file for error context.

    Returns:
        Duration in minutes as ``int``.

    Raises:
        ZoomParseError: If the value is not a non-negative number.
    """
    if isinstance(value, str) and value.strip().replace(".", "", 1).isdigit():
        value = float(value.strip())
    match value:
        case int() | float():
            if value >= 0:
                return int(value)
            raise ZoomParseError(
                filepath=filepath,
                reason=f"negative duration for {name!r}: {value}",
            )
        case _:
            raise ZoomParseError(
                filepath=filepath,
                reason=(
                    f"expected number for duration of {name!r}, "
                    f"got {type(value).__name__}: {value!r}"
                ),
            )


def _parse_yes_no(
    value: object,
    field: str,
    name: str,
    filepath: str,
) -> bool:
    """Parse a 'Yes'/'No' string cell into a boolean.

    Args:
        value: Raw cell value (expected ``"Yes"`` or ``"No"``).
        field: Field label for error messages.
        name: Participant name for error context.
        filepath: Source file for error context.

    Returns:
        ``True`` for ``"Yes"``, ``False`` for ``"No"``.

    Raises:
        ZoomParseError: If the value is not ``"Yes"`` or ``"No"``.
    """
    if isinstance(value, str):
        value = value.strip().capitalize()
    match value:
        case "Yes":
            return True
        case "No" | None:
            return False
        case _:
            raise ZoomParseError(
                filepath=filepath,
                reason=(
                    f"expected 'Yes' or 'No' for {field} of {name!r}, "
                    f"got {value!r}"
                ),
            )
