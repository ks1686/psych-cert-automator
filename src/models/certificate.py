"""CE certificate request and output models — internal value objects."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum, unique
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date

    from src.models.training import CEType

_NAME_PARTS_COUNT = 2
"""Number of parts expected when splitting a full name into first/last."""
_UNSAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9_-]+")


def _filename_part(value: str) -> str:
    cleaned = _UNSAFE_FILENAME_CHARS.sub("_", value.strip())
    return cleaned.strip("_") or "certificate"


@dataclass(frozen=True, slots=True)
class CERequest:
    """One person's CE credit request as captured by Qualtrics.

    Represents a single requested CE type from one survey response. A person
    may have multiple ``CERequest`` entries if they request multiple CE types.
    """

    name_on_certificate: str
    """Name as the person typed it (e.g., 'Jessica Benas')."""

    email: str | None
    """Preferred email address."""

    ce_type: CEType
    """CE type requested (e.g., 'APA', 'NASP', 'BCBA')."""

    license_number: str | None
    """License or certificate number, required by some CE types."""


@dataclass(frozen=True, slots=True)
class CertificateOutput:
    """Data that populates a single generated CE certificate."""

    full_name: str
    """Name as it appears on the certificate."""

    ce_type: CEType
    """CE type short code (e.g., 'APA')."""

    ce_credits: int
    """Number of CE credits awarded."""

    training_title: str
    """Title of the training session."""

    training_date: date
    """Date the training occurred."""

    instructor_name: str
    """Name of the instructor."""

    license_number: str | None
    """License or certificate number printed on the certificate (if applicable)."""

    issue_date: date
    """Date the certificate was generated."""

    @property
    def output_filename(self) -> str:
        """Computed output filename: ``{LastName}_{FirstName}_{CEType}_{Date}.pdf``.

        Derives first/last name from ``full_name`` by splitting on the last
        space. Single-word names use the word as both first and last.
        """
        parts = self.full_name.rsplit(" ", 1)
        if len(parts) == _NAME_PARTS_COUNT:
            first, last = parts[0], parts[1]
        else:
            first, last = "", parts[0]
        date_str = self.training_date.isoformat()
        filename_parts = [
            _filename_part(last),
            _filename_part(first),
            _filename_part(str(self.ce_type)),
            date_str,
        ]
        return "_".join(filename_parts) + ".pdf"


@unique
class EligibilityStatus(StrEnum):
    """Outcome of attendance validation for a CE request."""

    ELIGIBLE = "eligible"
    """Participant meets all attendance criteria."""

    NOT_FOUND_IN_ATTENDANCE = "not_found_in_attendance"
    """Qualtrics name not found in any Zoom attendance record."""

    ATTENDANCE_INSUFFICIENT = "attendance_insufficient"
    """Participant found but did not meet attendance requirements."""

    NAME_MATCH_AMBIGUOUS = "name_match_ambiguous"
    """Multiple possible Zoom matches — manual review required."""


@dataclass(frozen=True, slots=True)
class IneligibilityEntry:
    """Record of a CE request that could not be fulfilled, with diagnostics."""

    name_qualtrics: str
    """Name as it appeared in the Qualtrics export."""

    name_zoom: str | None
    """Matched Zoom name, if any."""

    match_status: str
    """Description of the match outcome."""

    late_join_minutes: int | None
    """Minutes late after session start (if applicable)."""

    early_leave_minutes: int | None
    """Minutes left before session end (if applicable)."""

    total_gaps_minutes: int | None
    """Cumulative unattended minutes (if applicable)."""

    rejected_ce_types: tuple[str, ...]
    """CE types requested that were rejected."""

    reason: str
    """Human-readable explanation for ineligibility."""

    status: EligibilityStatus
    """Categorical eligibility outcome."""


# ── Name matching result types ────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class MatchSuccess:
    """A single, unambiguous Zoom name match was found."""

    matched_name: str
    """The normalized Zoom name that matched."""

    confidence: float
    """Confidence score between 0.0 and 1.0."""


@dataclass(frozen=True, slots=True)
class MatchAmbiguous:
    """Multiple possible Zoom name matches were found."""

    candidates: tuple[str, ...]
    """All candidate Zoom names that could match."""


@dataclass(frozen=True, slots=True)
class MatchNotFound:
    """No Zoom attendance record matched the Qualtrics name."""


type MatchResult = MatchSuccess | MatchAmbiguous | MatchNotFound
"""Union type representing the outcome of name matching.

Possible variants:
    - ``MatchSuccess`` — one unambiguous match with confidence
    - ``MatchAmbiguous`` — multiple candidates, manual resolution needed
    - ``MatchNotFound`` — no Zoom record found
"""
