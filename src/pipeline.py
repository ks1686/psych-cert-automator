"""pipeline.py — full CE certificate generation pipeline orchestration.

Parse → Match → Validate → Classify → Generate → Report.

This module is importable by both the CLI entry point and programmatic callers.
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import TYPE_CHECKING, assert_never

from src.generator.certificate import generate_all
from src.generator.report import generate_ineligibility_report
from src.matcher.name_matcher import batch_match
from src.models.certificate import (
    CERequest,
    CertificateOutput,
    EligibilityStatus,
    IneligibilityEntry,
    MatchAmbiguous,
    MatchNotFound,
    MatchSuccess,
)
from src.parser.qualtrics import parse_qualtrics_export
from src.parser.zoom import ZoomParseError, parse_zoom_attendance
from src.validator.attendance import validate_attendance

if TYPE_CHECKING:
    from src.models.participant import ParticipantAttendance

logger = logging.getLogger(__name__)

_MIN_CSV_COLS = 2
"""Minimum columns expected in a manual-override CSV row."""


# ── Result type ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class PipelineResult:
    """Complete result of one CE certificate generation pipeline run.

    Fields:
        total_requests: Total number of CE requests found in the Qualtrics report.
        eligible: List of ``CertificateOutput`` for successfully generated certificates.
        ineligible: List of ``IneligibilityEntry`` for requests that could not be fulfilled.
        errors: Human-readable error messages (empty when no errors occurred).
    """

    total_requests: int
    eligible: list[CertificateOutput]
    ineligible: list[IneligibilityEntry]
    errors: list[str]


# ── Public entry point ─────────────────────────────────────────────────────────────


def run_pipeline(  # noqa: PLR0913
    zoom_path: str,
    qualtrics_path: str,
    title: str,
    training_date: date,
    instructor: str,
    ce_credits: int,
    ce_types: list[str],
    start_time: time,
    end_time: time,
    *,
    overrides_path: str | None = None,
    output_dir: str = "./output",
) -> PipelineResult:
    """Run the full CE certificate generation pipeline.

    Parse Zoom attendance and Qualtrics survey data, match names across the two
    sources with optional manual overrides, validate attendance, and generate
    PDF certificates plus an ineligibility report.

    Args:
        zoom_path: Path to the Zoom attendance ``.xlsx`` report.
        qualtrics_path: Path to the Qualtrics survey export ``.xlsx``.
        title: Training session title.
        training_date: Date the training occurred.
        instructor: Instructor name.
        ce_credits: Number of CE credits awarded for full attendance.
        ce_types: Short codes for CE types offered (e.g. ``['APA', 'NASP', 'BCBA']``).
        start_time: Scheduled session start time.
        end_time: Scheduled session end time.
        overrides_path: Optional path to a two-column CSV mapping Qualtrics names
            to Zoom names for manual name matching.
        output_dir: Directory where generated PDFs and reports are written.

    Returns:
        ``PipelineResult`` with counts, eligible/ineligible lists, and any errors.
        Does **not** call ``sys.exit()`` — errors are collected in the result.
    """
    errors: list[str] = []

    _ = (ce_types, start_time, end_time)  # accepted for future cross-validation

    try:
        # ── Steps 1-2: Parse reports ───────────────────────────────────────
        zoom_session = parse_zoom_attendance(zoom_path)
        ce_requests = parse_qualtrics_export(qualtrics_path)

        if not ce_requests:
            logger.info("No CE requests found in Qualtrics report.")
            return PipelineResult(
                total_requests=0,
                eligible=[],
                ineligible=[],
                errors=errors,
            )

        # ── Step 3: Load manual overrides ──────────────────────────────────
        overrides: dict[str, str] | None = None
        if overrides_path:
            overrides = _load_override_csv(overrides_path)

        # ── Step 4: Match names ────────────────────────────────────────────
        matches = batch_match(
            list(zoom_session.participants),
            ce_requests,
            overrides,
        )

        # ── Steps 5-6: Validate & classify ─────────────────────────────────
        session_start = zoom_session.session_start
        session_end = zoom_session.session_end

        eligible: list[CertificateOutput] = []
        ineligible: list[IneligibilityEntry] = []

        for request, participant, match_result in matches:
            match match_result:
                case MatchSuccess(matched_name=matched):
                    _handle_matched(
                        request,
                        participant,
                        matched,
                        session_start,
                        session_end,
                        title,
                        training_date,
                        instructor,
                        ce_credits,
                        eligible,
                        ineligible,
                    )
                case MatchAmbiguous(candidates=candidates):
                    ineligible.append(
                        _make_ineligible(
                            request,
                            name_zoom=", ".join(candidates),
                            match_status="ambiguous",
                            reason=f"Multiple Zoom matches: {', '.join(candidates)}",
                            status=EligibilityStatus.NAME_MATCH_AMBIGUOUS,
                        )
                    )
                case MatchNotFound():
                    ineligible.append(
                        _make_ineligible(
                            request,
                            name_zoom=None,
                            match_status="not found",
                            reason="Name not found in Zoom attendance",
                            status=EligibilityStatus.NOT_FOUND_IN_ATTENDANCE,
                        )
                    )
                case _:
                    assert_never(match_result)

        # ── Step 7: Generate certificates ──────────────────────────────────
        pdf_paths: list[str] = []
        if eligible:
            pdf_paths = generate_all(eligible, output_dir)

        # ── Step 9: Generate ineligibility report ──────────────────────────
        if ineligible:
            report_path = str(Path(output_dir) / "ineligibility_report.xlsx")
            _ = generate_ineligibility_report(ineligible, report_path)

        # ── Step 10: Log summary ───────────────────────────────────────────
        logger.info("Total CE requests: %d", len(ce_requests))
        logger.info("Eligible: %d", len(eligible))
        logger.info("Ineligible: %d", len(ineligible))
        logger.info("Certificates generated: %d", len(pdf_paths))

        return PipelineResult(
            total_requests=len(ce_requests),
            eligible=eligible,
            ineligible=ineligible,
            errors=errors,
        )

    except (FileNotFoundError, ZoomParseError, ValueError, KeyError, OSError) as exc:
        errors.append(str(exc))
        logger.exception("Pipeline failed with error")
        return PipelineResult(
            total_requests=0,
            eligible=[],
            ineligible=[],
            errors=errors,
        )


# ── Private helpers ─────────────────────────────────────────────────────────────────


def _load_override_csv(filepath: str) -> dict[str, str]:
    """Parse a two-column ``qualtrics_name,zoom_name`` CSV into a dict."""
    overrides: dict[str, str] = {}
    with Path(filepath).open(newline="", encoding="utf-8") as f:
        for row in csv.reader(f):
            if len(row) >= _MIN_CSV_COLS and row[0].strip() and row[1].strip():
                overrides[row[0].strip()] = row[1].strip()
    return overrides


def _int_or_none(value: float | None) -> int | None:
    """Return ``round(value)`` or ``None``."""
    return None if value is None else round(value)


def _make_ineligible(  # noqa: PLR0913
    request: CERequest,
    name_zoom: str | None,
    match_status: str,
    reason: str,
    status: EligibilityStatus,
    *,
    late_join: int | None = None,
    early_leave: int | None = None,
    total_gaps: int | None = None,
) -> IneligibilityEntry:
    """Build an ``IneligibilityEntry`` with common defaults filled."""
    return IneligibilityEntry(
        name_qualtrics=request.name_on_certificate,
        name_zoom=name_zoom,
        match_status=match_status,
        late_join_minutes=late_join,
        early_leave_minutes=early_leave,
        total_gaps_minutes=total_gaps,
        rejected_ce_types=(str(request.ce_type),),
        reason=reason,
        status=status,
    )


def _handle_matched(  # noqa: PLR0913
    request: CERequest,
    participant: ParticipantAttendance | None,
    matched_name: str,
    session_start: datetime,
    session_end: datetime,
    title: str,
    training_date: date,
    instructor: str,
    ce_credits: int,
    eligible: list[CertificateOutput],
    ineligible: list[IneligibilityEntry],
) -> None:
    """Validate attendance for a matched CE request and classify as eligible/ineligible."""
    if participant is None:
        ineligible.append(
            _make_ineligible(
                request,
                name_zoom=matched_name,
                match_status="matched",
                reason="Matched but no attendance data found",
                status=EligibilityStatus.NOT_FOUND_IN_ATTENDANCE,
            )
        )
        return

    validation = validate_attendance(participant, session_start, session_end)

    if validation.is_eligible:
        eligible.append(
            CertificateOutput(
                full_name=request.name_on_certificate,
                ce_type=request.ce_type,
                ce_credits=ce_credits,
                training_title=title,
                training_date=training_date,
                instructor_name=instructor,
                license_number=request.license_number,
                issue_date=date.today(),  # noqa: DTZ011
            )
        )
    else:
        ineligible.append(
            _make_ineligible(
                request,
                name_zoom=matched_name,
                match_status="matched",
                reason=validation.failure_reason or "Attendance insufficient",
                status=EligibilityStatus.ATTENDANCE_INSUFFICIENT,
                late_join=_int_or_none(validation.late_join_minutes),
                early_leave=_int_or_none(validation.early_leave_minutes),
                total_gaps=_int_or_none(validation.mid_session_gaps_minutes),
            )
        )
