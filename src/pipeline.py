"""pipeline.py — full CE certificate generation pipeline orchestration.

Parse → Match → Validate → Classify → Generate → Report.

This module is importable by both the CLI entry point and programmatic callers.
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, assert_never

from src.generator.certificate import (
    CertificateRenderOptions,
    certificate_warnings,
    generate_all,
)
from src.generator.report import generate_ineligibility_report, next_free_path
from src.generator.templates import resolve_template_key
from src.generator.zoom_host import host_matches_name
from src.matcher.name_matcher import CONFIRMED_CONFIDENCE, batch_match
from src.models.certificate import (
    CERequest,
    CertificateOutput,
    EligibilityStatus,
    IneligibilityEntry,
    MatchAmbiguous,
    MatchNotFound,
    MatchSuccess,
    allocate_unique_basenames,
)
from src.models.participant import extract_name_tokens, normalize_name
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
        generated_paths: Absolute paths to generated certificate files (PDF or DOCX).
    """

    total_requests: int
    eligible: list[CertificateOutput]
    ineligible: list[IneligibilityEntry]
    errors: list[str]
    generated_paths: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    """Certificates that were generated but should be checked by a person."""


def _same_person_and_type(older: CERequest, newer: CERequest) -> bool:
    """True when two requests are the same person asking for the same CE type.

    Names must match and emails must not conflict. Normalized names that are
    equal match when at least one email is missing or both are equal. A name
    that only adds or drops a word ("Ann M. Lee" vs "Ann Lee") matches only
    when both rows carry the same email. A shared email alone (a family
    address) never makes two different names one person.
    """
    if str(older.ce_type) != str(newer.ce_type):
        return False
    old_email = (older.email or "").strip().casefold()
    new_email = (newer.email or "").strip().casefold()
    if old_email and new_email and old_email != new_email:
        return False
    old_name = normalize_name(older.name_on_certificate)
    new_name = normalize_name(newer.name_on_certificate)
    if not old_name or not new_name:
        return False
    if old_name == new_name:
        return True
    if not (old_email and new_email):
        return False
    old_tokens = extract_name_tokens(old_name)
    new_tokens = extract_name_tokens(new_name)
    return old_tokens <= new_tokens or new_tokens <= old_tokens


def _submitted_sort_key(request: CERequest) -> float:
    """Sortable submission time; untimed requests sort first (see caller)."""
    return request.submitted_at.timestamp() if request.submitted_at else 0.0


def split_duplicates(
    requests: list[CERequest],
) -> tuple[list[CERequest], list[CERequest]]:
    """Split survey rows into the ones to use and older duplicates.

    Two requests are duplicates when ``_same_person_and_type`` says so.
    "Latest" is the most recent ``submitted_at``; requests without a time
    count as older than timed ones, and ties keep the later row. Both lists
    keep the original row order.
    """
    order = sorted(
        range(len(requests)),
        key=lambda i: (
            requests[i].submitted_at is not None,
            _submitted_sort_key(requests[i]),
            i,
        ),
    )
    kept: list[int] = []
    dropped: list[int] = []
    for i in order:
        older = [j for j in kept if _same_person_and_type(requests[j], requests[i])]
        for j in older:
            kept.remove(j)
            dropped.append(j)
        kept.append(i)
    if dropped:
        logger.info("Ignored %d duplicate survey submission(s).", len(dropped))
    return [requests[i] for i in sorted(kept)], [requests[i] for i in sorted(dropped)]


def dedupe_requests(requests: list[CERequest]) -> list[CERequest]:
    """Drop duplicate survey submissions, keeping the latest one (see ``split_duplicates``)."""
    return split_duplicates(requests)[0]


def session_window(
    meeting_start: datetime,
    meeting_end: datetime,
    start_time: time | None,
    end_time: time | None,
) -> tuple[datetime, datetime]:
    """Return the window attendance is judged against (see ``judged_window``)."""
    start, end, _ = judged_window(meeting_start, meeting_end, start_time, end_time)
    return start, end


REPORT_FILENAME = "ineligibility_report.xlsx"


def rerun_warnings(
    eligible: list[CertificateOutput],
    generated_paths: list[str],
    report_path: Path | None,
) -> list[str]:
    """Say which file is current when a rerun had to add a ``_2`` suffix.

    Files are never overwritten, so a second run into the same folder writes
    ``X_2.pdf`` next to the older ``X.pdf``; without this, nothing tells the
    person which of the two to send.
    """
    warnings: list[str] = []
    planned = allocate_unique_basenames(eligible)
    for stem, generated in zip(planned, generated_paths, strict=False):
        path = Path(generated)
        if path.stem != stem:
            older = f"{stem}{path.suffix}"
            warnings.append(
                f"{older} already existed in the output folder, so this run wrote "
                f"{path.name}; {path.name} is the current file.",
            )
    if report_path is not None and report_path.name != REPORT_FILENAME:
        warnings.append(
            f"{REPORT_FILENAME} already existed in the output folder, so this run wrote "
            f"{report_path.name}; {report_path.name} is the current report.",
        )
    return warnings


def judged_window(
    meeting_start: datetime,
    meeting_end: datetime,
    start_time: time | None,
    end_time: time | None,
    *,
    clip_to_meeting: bool = True,
) -> tuple[datetime, datetime, str | None]:
    """Return the attendance window and a warning when Zoom and the entry disagree.

    The window is the overlap of the entered session times and the Zoom
    meeting. Hosts often open the meeting early and close it late, so the
    entered times usually win. When the Zoom meeting started after the
    entered start or ended before the entered end (for example it ended at
    11:40 for a 9:00 to 12:00 session), nobody could attend the missing part,
    so only the overlap is judged and a warning says so.

    The entered times are placed on the Zoom meeting's date (multi-day events
    use the date of the uploaded report). An end time at or before the start
    rolls to the next day. Without entered times the Zoom meeting window is
    used. ``clip_to_meeting=False`` skips the overlap for callers whose
    "meeting" window is only a guess. If the two windows do not overlap at
    all, the entered times are used and the warning says so.
    """
    if start_time is None or end_time is None:
        return meeting_start, meeting_end, None
    day = meeting_start.date()
    entered_start = datetime.combine(day, start_time, tzinfo=meeting_start.tzinfo)
    entered_end = datetime.combine(day, end_time, tzinfo=meeting_start.tzinfo)
    if entered_end <= entered_start:
        entered_end += timedelta(days=1)
    if not clip_to_meeting:
        return entered_start, entered_end, None

    start = max(entered_start, meeting_start)
    end = min(entered_end, meeting_end)
    if (start, end) == (entered_start, entered_end):
        return start, end, None

    zoom_text = f"{meeting_start:%H:%M} to {meeting_end:%H:%M}"
    entered_text = f"{entered_start:%H:%M} to {entered_end:%H:%M}"
    if end <= start:
        return (
            entered_start,
            entered_end,
            f"The Zoom meeting ran {zoom_text}, which does not overlap the session "
            f"entered as {entered_text}. Attendance was judged from {entered_text}; "
            "check the session date and times.",
        )
    return (
        start,
        end,
        f"The Zoom meeting ran {zoom_text}, but the session was entered as "
        f"{entered_text}. Attendance was judged from {start:%H:%M} to {end:%H:%M}.",
    )


# ── Public entry point ─────────────────────────────────────────────────────────────


def run_pipeline(  # noqa: PLR0913
    zoom_path: str,
    qualtrics_path: str,
    title: str,
    training_date: date,
    instructor: str,
    ce_credits: float,
    ce_types: list[str],
    start_time: time,
    end_time: time,
    *,
    overrides: dict[str, str] | None = None,
    overrides_path: str | None = None,
    output_dir: str = "./output",
    excluded_names: set[str] | None = None,
    is_virtual: bool = True,
    location: str | None = None,
    end_date: date | None = None,
    exclude_host: bool = False,
) -> PipelineResult:
    """Run the full CE certificate generation pipeline.

    Parse Zoom attendance and Qualtrics survey data, match names across the two
    sources with optional manual overrides, validate attendance, and generate
    certificates from official Word templates (PDF when a converter is available).

    Args:
        zoom_path: Path to the Zoom attendance ``.xlsx`` report.
        qualtrics_path: Path to the Qualtrics survey export ``.xlsx``.
        title: Training session title.
        training_date: Date the training occurred (or range start for multi-day).
        instructor: Instructor name.
        ce_credits: Number of CE credits awarded for full attendance.
        ce_types: Short codes for CE types offered (e.g. ``['APA', 'NASP', 'NY', 'NBCC']``).
        start_time: Scheduled session start time.
        end_time: Scheduled session end time.
        overrides: Optional in-memory mapping from Qualtrics names to Zoom names.
        overrides_path: Optional path to a two-column CSV mapping Qualtrics names
            to Zoom names for manual name matching.
        output_dir: Directory where generated files and reports are written.
        excluded_names: Qualtrics certificate names to skip (host/stragglers).
        is_virtual: When True, use virtual Location/Format template strings.
        location: In-person location text (ignored when ``is_virtual``).
        end_date: Optional multi-day end date for the certificate date range.
        exclude_host: When True, leave out survey names that look like the
            Zoom meeting host (the desktop app does this on its review step).

    Returns:
        ``PipelineResult`` with counts, eligible/ineligible lists, generated
        paths, and any errors. Does **not** call ``sys.exit()``.
    """
    errors: list[str] = []
    skip_names = {name.strip() for name in (excluded_names or set()) if name.strip()}
    render_options = CertificateRenderOptions(
        is_virtual=is_virtual,
        location=location,
        end_date=end_date,
        session_start=start_time,
        session_end=end_time,
    )

    offered_keys = _offered_template_keys(ce_types)

    try:
        # ── Steps 1-2: Parse reports ───────────────────────────────────────
        zoom_session = parse_zoom_attendance(zoom_path)
        all_requests = parse_qualtrics_export(qualtrics_path)
        ce_requests, duplicates = split_duplicates(all_requests)

        if not ce_requests:
            logger.info("No CE requests found in Qualtrics report.")
            return PipelineResult(
                total_requests=0,
                eligible=[],
                ineligible=[],
                errors=errors,
            )

        if exclude_host and zoom_session.host:
            host_names = {
                r.name_on_certificate
                for r in ce_requests
                if host_matches_name(zoom_session.host, r.name_on_certificate)
            }
            if host_names:
                logger.info("Excluding Zoom host: %s", ", ".join(sorted(host_names)))
                skip_names |= host_names

        # ── Step 3: Load manual overrides ──────────────────────────────────
        manual_overrides = overrides
        if overrides_path:
            loaded_overrides = _load_override_csv(overrides_path)
            manual_overrides = {
                **(manual_overrides or {}),
                **loaded_overrides,
            }

        # ── Step 4: Match names ────────────────────────────────────────────
        matches = batch_match(
            list(zoom_session.participants),
            ce_requests,
            manual_overrides,
        )

        window_start, window_end, window_warning = judged_window(
            zoom_session.session_start,
            zoom_session.session_end,
            start_time,
            end_time,
        )
        eligible, ineligible = _classify_requests(
            matches,
            skip_names=skip_names,
            offered_keys=offered_keys,
            session_start=window_start,
            session_end=window_end,
            title=title,
            training_date=training_date,
            instructor=instructor,
            ce_credits=ce_credits,
        )
        ineligible.extend(_duplicate_entry(request) for request in duplicates)

        # ── Step 7: Generate certificates ──────────────────────────────────
        generated_paths: list[str] = []
        if eligible:
            generated_paths = generate_all(
                eligible,
                output_dir,
                options=render_options,
            )

        # ── Step 9: Generate ineligibility report ──────────────────────────
        report_path: Path | None = None
        if ineligible:
            report_path = next_free_path(Path(output_dir) / REPORT_FILENAME)
            _ = generate_ineligibility_report(ineligible, str(report_path))

        # ── Step 10: Log summary ───────────────────────────────────────────
        logger.info("Total CE requests: %d", len(all_requests))
        logger.info("Eligible: %d", len(eligible))
        logger.info("Ineligible: %d", len(ineligible))
        logger.info("Certificates generated: %d", len(generated_paths))

        return PipelineResult(
            total_requests=len(all_requests),
            eligible=eligible,
            ineligible=ineligible,
            errors=errors,
            generated_paths=generated_paths,
            warnings=[
                *([window_warning] if window_warning else []),
                *rerun_warnings(eligible, generated_paths, report_path),
                *(
                    warning
                    for cert, path in zip(eligible, generated_paths, strict=False)
                    for warning in certificate_warnings(cert, path)
                ),
            ],
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


def _ambiguous_reason(
    candidates: tuple[str, ...],
    matches: list[tuple[CERequest, ParticipantAttendance | None, object]],
) -> str:
    """Why a request could not be tied to one Zoom attendee."""
    if len(candidates) != 1:
        return f"Multiple Zoom matches: {', '.join(candidates)}"
    [zoom_name] = candidates
    zoom_email = next(
        (p.email for _r, p, _m in matches if p is not None and p.name_raw == zoom_name and p.email),
        None,
    )
    joined_as = f"{zoom_name} ({zoom_email})" if zoom_email else zoom_name
    return (
        f"The Zoom attendee {joined_as} also matches another request from a different "
        "person with the same name, so it is not clear whose attendance it is. Check "
        "who attended and include this person by hand if they did."
    )


def _classify_requests(  # noqa: PLR0913
    matches: list[tuple[CERequest, ParticipantAttendance | None, object]],
    *,
    skip_names: set[str],
    offered_keys: set[str],
    session_start: datetime,
    session_end: datetime,
    title: str,
    training_date: date,
    instructor: str,
    ce_credits: float,
) -> tuple[list[CertificateOutput], list[IneligibilityEntry]]:
    eligible: list[CertificateOutput] = []
    ineligible: list[IneligibilityEntry] = []
    for request, participant, match_result in matches:
        if request.name_on_certificate.strip() in skip_names:
            ineligible.append(
                _make_ineligible(
                    request,
                    name_zoom=None,
                    match_status="excluded",
                    reason="Excluded from certificate generation",
                    status=EligibilityStatus.EXCLUDED,
                )
            )
            continue
        if _is_unoffered_specialty(request, offered_keys):
            ineligible.append(
                _make_ineligible(
                    request,
                    name_zoom=None,
                    match_status="not offered",
                    reason=f"CE type not offered: {request.ce_type}",
                    status=EligibilityStatus.CE_TYPE_NOT_OFFERED,
                )
            )
            continue
        match match_result:
            case MatchSuccess(matched_name=matched, confidence=conf) if conf < CONFIRMED_CONFIDENCE:
                ineligible.append(
                    _make_ineligible(
                        request,
                        name_zoom=matched,
                        match_status="needs review",
                        reason=(
                            f"Needs review: partial name match to Zoom {matched!r} "
                            f"({round(conf * 100)}%). Confirm it in Review Matches "
                            "or add a manual override."
                        ),
                        status=EligibilityStatus.NEEDS_REVIEW,
                    )
                )
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
                        reason=_ambiguous_reason(candidates, matches),
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
    return eligible, ineligible


def _offered_template_keys(ce_types: list[str]) -> set[str]:
    return {resolve_template_key(code) for code in ce_types if code.strip()}


def _is_unoffered_specialty(request: CERequest, offered_keys: set[str]) -> bool:
    request_key = resolve_template_key(str(request.ce_type))
    return request_key in {"apa", "ny", "nasp", "nbcc"} and request_key not in offered_keys


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


def _duplicate_entry(request: CERequest) -> IneligibilityEntry:
    when = (
        f" (submitted {request.submitted_at:%Y-%m-%d %H:%M})" if request.submitted_at else ""
    )
    return _make_ineligible(
        request,
        name_zoom=None,
        match_status="duplicate",
        reason=(
            f"Duplicate submission{when}: a later response from the same person "
            "for the same CE type was used instead."
        ),
        status=EligibilityStatus.DUPLICATE_SUBMISSION,
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
    ce_credits: float,
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
