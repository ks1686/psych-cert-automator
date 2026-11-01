"""Zoom participant and attendance data models — internal value objects."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import TYPE_CHECKING, NewType, override

if TYPE_CHECKING:
    from datetime import datetime


Minutes = NewType("Minutes", int)
"""Branded integer type for minute durations."""


@dataclass(frozen=True, slots=True)
class ParticipantDataError(Exception):
    """Error for invalid participant or attendance data.

    Carries the raw name involved and a human-readable reason so callers can
    surface precise diagnostics.
    """

    name_raw: str
    reason: str

    @override
    def __str__(self) -> str:
        """Return a human-readable error message."""
        return f"Participant data error for {self.name_raw!r}: {self.reason}"


@dataclass(frozen=True, slots=True)
class AttendanceRecord:
    """One Zoom join/leave segment for a participant."""

    name_raw: str
    """Original name as reported by Zoom (may include titles, pronouns, etc.)."""

    email: str | None
    """Email associated with the participant. Often empty for guests."""

    join_time: datetime
    """When the participant joined this segment."""

    leave_time: datetime
    """When the participant left this segment."""

    duration_minutes: int
    """Duration of this specific segment in minutes."""

    is_guest: bool
    """Whether this participant joined as a guest."""

    is_waiting_room: bool
    """Whether this segment represents time spent in the waiting room.

    Waiting-room segments are excluded from attendance computation.
    """


@dataclass(frozen=True, slots=True)
class ParticipantAttendance:
    """Aggregated attendance data for one person across all Zoom segments."""

    name_raw: str
    """Original name from Zoom (from the first non-waiting-room segment)."""

    segments: tuple[AttendanceRecord, ...]
    """Non-waiting-room segments, sorted by join_time ascending."""

    first_join: datetime
    """Earliest join time across all non-waiting-room segments."""

    last_leave: datetime
    """Latest leave time across all non-waiting-room segments."""

    total_attended_minutes: Minutes
    """Sum of duration_minutes across all non-waiting-room segments."""

    email: str | None = None
    """First non-empty email across the segments (used as a match tiebreaker)."""

    @classmethod
    def from_records(cls, records: list[AttendanceRecord]) -> ParticipantAttendance:
        """Build aggregated attendance from a list of raw segment records.

        Filters out waiting-room segments and sorts by join time. Raises
        ``ParticipantDataError`` if no valid segments remain after filtering.

        Args:
            records: Raw per-segment records for one person (may include
                waiting-room entries).

        Returns:
            Aggregated attendance with computed first_join, last_leave, and
            total_attended_minutes.

        Raises:
            ParticipantDataError: If all records are waiting-room entries
                (i.e., no real attendance data remains).
        """
        valid_segments = sorted(
            (r for r in records if not r.is_waiting_room),
            key=lambda r: r.join_time,
        )

        if not valid_segments:
            name = records[0].name_raw if records else "<unknown>"
            raise ParticipantDataError(
                name_raw=name,
                reason="no non-waiting-room attendance records",
            )

        first_join = min(r.join_time for r in valid_segments)
        last_leave = max(r.leave_time for r in valid_segments)
        total = sum(r.duration_minutes for r in valid_segments)

        email = next((r.email.strip() for r in valid_segments if r.email and r.email.strip()), None)

        return cls(
            name_raw=valid_segments[0].name_raw,
            segments=tuple(valid_segments),
            first_join=first_join,
            last_leave=last_leave,
            total_attended_minutes=Minutes(total),
            email=email,
        )


# ── Name normalisation utilities ─────────────────────────────────────────────


_CREDENTIALS = frozenset(
    {
        "phd", "psyd", "edd", "msw", "lcsw", "lpc", "lmft", "med", "mba", "bsn",
        "lsw", "lmhc", "lcpc", "lpcc", "ncc", "ncsp", "bcba", "dsw", "dnp",
        "aprn", "lcat", "msed", "mse", "cas", "lac", "lcadc", "rpt",
    }
)
"""Credentials that are never surnames, matched case-insensitively."""

_SURNAME_LIKE_CREDENTIALS = frozenset({"ma", "ms", "md", "jd", "pa", "np", "rn"})
"""Credentials that are also real surnames (Li Ma, Rosa Pa).

These are stripped only when written in capitals (``MA``, ``M.A.``), so a
title-case surname such as ``Ma`` is always kept.
"""

_HONORIFICS = frozenset({"dr", "mr", "mrs", "ms", "mx", "miss", "prof"})
"""Leading honorifics dropped from the front of a name."""

_APOSTROPHES = str.maketrans(dict.fromkeys("\u2019\u2018\u02bc\u0060\u00b4\u2032", "'"))
"""Curly and look-alike apostrophes folded to ASCII ``'``."""

_PAREN_CONTENT = re.compile(r"\([^)]*\)")
"""Pattern matching parenthetical content (pronouns, display names, emails)."""

_TOKEN_SPLIT = re.compile(r"[\s\-\u2010-\u2015]+")
"""Whitespace and hyphen runs that separate name tokens."""

_TOKEN_STRIP = re.compile(r"[.'#]")
"""Characters removed inside a token (``Ph.D.`` -> ``phd``, ``O'Neil`` -> ``oneil``)."""

_MIN_NAME_TOKENS = 2
"""Trailing credentials are only stripped while a full name (2 tokens) remains."""


def fold_text(raw: str) -> str:
    """Apply NFKC, ASCII apostrophes, and accent folding (case preserved)."""
    text = unicodedata.normalize("NFKC", raw).translate(_APOSTROPHES)
    decomposed = unicodedata.normalize("NFD", text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return unicodedata.normalize("NFC", stripped)


def _clean_token(token: str) -> str:
    return _TOKEN_STRIP.sub("", token).casefold()


def _is_credential(token: str, *, all_caps_name: bool = False) -> bool:
    """True for a degree or license token.

    Credentials that double as surnames count only when written in capitals,
    and never when the whole name is in capitals (``KIM LI MA``), because
    then capitals say nothing about the token.
    """
    key = _clean_token(token)
    if key in _CREDENTIALS:
        return True
    if key in _SURNAME_LIKE_CREDENTIALS and not all_caps_name:
        letters = token.replace(".", "")
        return letters.isupper()
    return False


def _is_all_caps(tokens: list[str]) -> bool:
    letters = "".join(ch for token in tokens for ch in token if ch.isalpha())
    return len(tokens) > 1 and letters.isupper()


def _split_tokens(text: str) -> list[str]:
    return [t for t in _TOKEN_SPLIT.split(text) if _clean_token(t)]


def normalize_name(raw: str) -> str:
    """Normalize a raw Zoom or Qualtrics name for matching purposes.

    Steps, in order:
        1. NFKC, curly apostrophes to ``'``, and accent folding
           (``José Núñez`` and ``Jose Nunez`` agree; NFC and NFD agree).
        2. Strip parenthetical content (pronouns, display names, emails) and
           the ``#`` guest marker.
        3. Drop comma-separated segments made only of credentials
           (``Pat Smith, M.A., LPC``).
        4. Drop leading honorifics (``Dr.``) and trailing credentials, but
           only while at least a two-token name remains. Credentials that
           double as surnames (MA, PA, NP, RN, MS, JD, MD) are only dropped
           when written in capitals, so ``Li Ma`` stays ``li ma``, and never
           from a name typed all in capitals (``KIM LI MA``).
        5. Remove periods and apostrophes inside tokens, treat hyphens as
           spaces, collapse whitespace, and casefold.

    Args:
        raw: The original name string (e.g. ``"Dr. Patricia A. Farrell"``).

    Returns:
        Normalized tokens joined by single spaces (``"patricia a farrell"``).
    """
    text = _PAREN_CONTENT.sub(" ", fold_text(raw)).replace("#", " ")
    kept = _credential_free_segments(text)
    return " ".join(_clean_token(t) for t in _name_tokens(kept))


def _credential_free_segments(text: str) -> list[str]:
    """Comma segments of ``text``, minus those made only of credentials."""
    segments = text.split(",")
    kept = [segments[0]]
    for segment in segments[1:]:
        tokens = _split_tokens(segment)
        if tokens and all(_is_credential(t) for t in tokens):
            continue
        kept.append(segment)
    return kept


def _name_tokens(segments: list[str]) -> list[str]:
    """Tokens without leading honorifics or trailing credentials (case kept)."""
    tokens = _split_tokens(" ".join(segments))
    while len(tokens) > 1 and _clean_token(tokens[0]) in _HONORIFICS:
        tokens.pop(0)
    caps = _is_all_caps(tokens)
    while len(tokens) > _MIN_NAME_TOKENS and _is_credential(tokens[-1], all_caps_name=caps):
        tokens.pop()
    return tokens


def surname(raw: str) -> str:
    """Last name as written, ignoring honorifics and credentials.

    ``"Mark Roe, Ph.D."`` and ``"Dr. Mark Roe PhD"`` give ``"Roe"``. Returns
    an empty string when nothing is left.
    """
    text = _PAREN_CONTENT.sub(" ", raw).replace("#", " ")
    tokens = _name_tokens(_credential_free_segments(text))
    # Two-token names keep a trailing credential in normalize_name (it may be
    # a surname); for a filename prefer the token before an unambiguous one.
    if len(tokens) == _MIN_NAME_TOKENS and _clean_token(tokens[-1]) in _CREDENTIALS:
        tokens.pop()
    return tokens[-1].strip(".,") if tokens else ""


def extract_name_tokens(normalized: str) -> frozenset[str]:
    """Extract word-level tokens from an already-normalized name.

    Args:
        normalized: A name string already processed by ``normalize_name()``.

    Returns:
        Frozenset of lowercase word tokens (e.g.,
        ``frozenset({'patricia', 'a', 'farrell'})``).
    """
    return frozenset(normalized.split())
