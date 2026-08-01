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
# Keep only portable filename characters (safe on Windows, macOS, and Linux).
_UNSAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9_-]+")
_WINDOWS_RESERVED = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }
)


def _filename_part(value: str) -> str:
    cleaned = _UNSAFE_FILENAME_CHARS.sub("_", value.strip())
    cleaned = cleaned.strip("._") or "certificate"
    if cleaned.upper() in _WINDOWS_RESERVED:
        return f"_{cleaned}"
    return cleaned


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
    def output_basename(self) -> str:
        """Filename stem: ``{LastName}_CECertificate_{InstructorLast}_{Date}``.

        Recipient and instructor last names are taken from the final whitespace-
        separated token. Unsafe characters (including ``@``) are sanitized.
        """
        recipient_last = _last_name(self.full_name)
        instructor_last = _last_name(self.instructor_name)
        date_str = self.training_date.isoformat()
        return "_".join(
            [
                _filename_part(recipient_last),
                "CECertificate",
                _filename_part(instructor_last),
                date_str,
            ]
        )

    @property
    def output_filename(self) -> str:
        """Preferred PDF filename (``output_basename`` + ``.pdf``)."""
        return f"{self.output_basename}.pdf"


def _last_name(full_name: str) -> str:
    """Return the last whitespace-separated token of a person name."""
    parts = full_name.strip().rsplit(" ", 1)
    if len(parts) == _NAME_PARTS_COUNT:
        return parts[1]
    return parts[0] if parts and parts[0] else "Unknown"


def _first_name(full_name: str) -> str:
    """Return everything before the last whitespace-separated token."""
    parts = full_name.strip().rsplit(" ", 1)
    if len(parts) == _NAME_PARTS_COUNT:
        return parts[0]
    return ""


def allocate_unique_basenames(outputs: list[CertificateOutput]) -> list[str]:
    """Assign unique filename stems for a certificate batch.

    Prefers ``{Last}_CECertificate_{InstructorLast}_{Date}``. On collision
    (same last name, identical full names, or multiple CE types), disambiguates
    with first name, then CE type, then a numeric suffix.
    """
    used: set[str] = set()
    assigned: list[str] = []
    for output in outputs:
        for candidate in _basename_candidates(output):
            if candidate not in used:
                used.add(candidate)
                assigned.append(candidate)
                break
        else:
            # Extremely unlikely: all candidates taken — numeric fallback.
            n = 2
            base = output.output_basename
            while f"{base}_{n}" in used:
                n += 1
            chosen = f"{base}_{n}"
            used.add(chosen)
            assigned.append(chosen)
    return assigned


def _basename_candidates(output: CertificateOutput) -> list[str]:
    preferred = output.output_basename
    recipient_last = _filename_part(_last_name(output.full_name))
    recipient_first = _filename_part(_first_name(output.full_name))
    instructor_last = _filename_part(_last_name(output.instructor_name))
    date_str = output.training_date.isoformat()
    ce_part = _filename_part(str(output.ce_type))

    with_first = "_".join(
        part
        for part in (
            recipient_last,
            recipient_first or None,
            "CECertificate",
            instructor_last,
            date_str,
        )
        if part
    )
    return [
        preferred,
        with_first,
        f"{preferred}_{ce_part}",
        f"{with_first}_{ce_part}",
    ]


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

    EXCLUDED = "excluded"
    """User excluded this person from certificate generation."""


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
