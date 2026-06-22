"""certgen.py — CLI entry point wiring Zoom+Qualtrics parse -> match -> validate -> generate."""

from __future__ import annotations

import csv
import sys
from datetime import date, datetime, time
from pathlib import Path
from typing import TYPE_CHECKING, assert_never

import click
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


_MIN_CSV_COLS = 2
"""Minimum columns expected in a manual-override CSV row."""


# ── Private helpers ───────────────────────────────────────────────────────────────


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


# ── CLI entry point ──────────────────────────────────────────────────────────────


@click.command()
@click.option("--title", required=True, help="Training title")
@click.option("--date", "training_date_str", required=True, help="Training date (YYYY-MM-DD)")
@click.option("--instructor", required=True, help="Instructor name")
@click.option("--ce-credits", type=int, required=True, help="Number of CE credits")
@click.option(
    "--ce-types",
    required=True,
    help="Comma-separated CE types offered (e.g. APA,NASP,BCBA)",
)
@click.option("--start-time", required=True, help="Session start time (HH:MM)")
@click.option("--end-time", required=True, help="Session end time (HH:MM)")
@click.option("--zoom-report", type=click.Path(exists=True), required=True)
@click.option("--qualtrics-report", type=click.Path(exists=True), required=True)
@click.option("--output-dir", type=click.Path(), default="./output")
@click.option(
    "--manual-overrides",
    type=click.Path(exists=True),
    help="CSV of Qualtrics name → Zoom name overrides",
)
def main(  # noqa: C901, PLR0913
    title: str,
    training_date_str: str,
    instructor: str,
    ce_credits: int,
    ce_types: str,
    start_time: str,
    end_time: str,
    zoom_report: str,
    qualtrics_report: str,
    output_dir: str,
    manual_overrides: str | None,
) -> None:
    """Generate CE certificates from Zoom attendance and Qualtrics survey data.

    Full pipeline: parse → match → validate → generate → report.
    """
    try:
        # ── Parse boundary inputs ──────────────────────────────────────────
        training_date = date.fromisoformat(training_date_str)
        _ = time.fromisoformat(start_time)  # validate format
        _ = time.fromisoformat(end_time)    # validate format

        ce_type_codes = [t.strip() for t in ce_types.split(",") if t.strip()]
        if not ce_type_codes:
            click.echo("Error: --ce-types must not be empty", err=True)
            sys.exit(1)

        # ── Steps 1-2: Parse reports ───────────────────────────────────────
        zoom_session = parse_zoom_attendance(zoom_report)
        ce_requests = parse_qualtrics_export(qualtrics_report)

        if not ce_requests:
            click.echo("No CE requests found in Qualtrics report.")
            sys.exit(0)

        # ── Step 3: Load manual overrides ──────────────────────────────────
        overrides: dict[str, str] | None = None
        if manual_overrides:
            overrides = _load_override_csv(manual_overrides)

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

        # ── Step 10: Print summary ─────────────────────────────────────────
        click.echo(f"Total CE requests: {len(ce_requests)}")
        click.echo(f"Eligible: {len(eligible)}")
        click.echo(f"Ineligible: {len(ineligible)}")
        click.echo(f"Certificates generated: {len(pdf_paths)}")

    except (FileNotFoundError, ZoomParseError, ValueError, KeyError, OSError) as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)


# ── Pipeline step helpers ────────────────────────────────────────────────────────


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


if __name__ == "__main__":
    main()
