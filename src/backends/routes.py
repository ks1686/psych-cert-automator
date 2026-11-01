"""API routes for the CE certificate generation pipeline.

Five endpoints wrapping the existing pipeline, parser, matcher, and generator:

    POST /api/parse        — parse Zoom + Qualtrics reports
    POST /api/match        — match Qualtrics names to Zoom participants
    POST /api/preview      — generate a single certificate preview
    POST /api/generate     — run the full pipeline (JSON result)
    POST /api/download-zip — bundle certificate files into a ZIP archive
"""

from __future__ import annotations

import asyncio
import io
import json
import secrets
import tempfile
import zipfile
from datetime import date, datetime, time
from pathlib import Path
from typing import Literal, assert_never

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from src.generator.certificate import (
    CertificateRenderOptions,
    certificate_warnings,
    generate_certificate,
)
from src.matcher.name_matcher import CONFIRMED_CONFIDENCE, match_requests, person_groups
from src.models.certificate import (
    CertificateOutput,
    MatchAmbiguous,
    MatchNotFound,
    MatchSuccess,
)
from src.models.credits import CECredits
from src.models.participant import AttendanceRecord, ParticipantAttendance
from src.models.training import CEType
from src.parser.qualtrics import parse_qualtrics_export
from src.parser.tabular import UnreadableFileError
from src.parser.zoom import ZoomParseError, parse_zoom_attendance
from src.pipeline import PipelineResult, dedupe_requests, judged_window, run_pipeline
from src.validator.attendance import validate_attendance

router = APIRouter()
_GENERATED_FILES: dict[str, Path] = {}
_ALLOWED_CERT_SUFFIXES = frozenset({".pdf", ".docx"})


# ═══════════════════════════════════════════════════════════════════════════
# Request / Response wire types (inline — T8 will extract to schemas.py)
# ═══════════════════════════════════════════════════════════════════════════


class ParseRequest(BaseModel):
    """Body for ``POST /api/parse``."""

    zoom_path: str
    qualtrics_path: str


class ParseParticipant(BaseModel):
    """Serialisable participant summary from Zoom attendance."""

    name_raw: str
    first_join: str
    last_leave: str
    total_attended_minutes: int
    segment_count: int


class ParseCERequest(BaseModel):
    """Serialisable CE-request summary from Qualtrics."""

    name_on_certificate: str
    email: str | None
    ce_type: str
    license_number: str | None


class ParseResponse(BaseModel):
    """Response for ``POST /api/parse``."""

    session_start: str
    session_end: str
    participants: list[ParseParticipant]
    ce_requests: list[ParseCERequest]
    participant_count: int
    request_count: int
    zoom_host: str | None = None


class MatchParticipantBrief(BaseModel):
    """Minimal Zoom participant entry for the match endpoint."""

    name: str
    first_join: datetime
    last_leave: datetime
    total_attended_minutes: int
    segments_count: int


class MatchCERequestBrief(BaseModel):
    """Minimal CE-request entry for the match endpoint."""

    name_on_certificate: str
    ce_type: str
    email: str | None = None
    license_number: str | None = None


class MatchRequest(BaseModel):
    """Body for ``POST /api/match``."""

    zoom_participants: list[MatchParticipantBrief]
    ce_requests: list[MatchCERequestBrief]
    overrides: dict[str, str] | None = None
    session_start: datetime | None = None
    session_end: datetime | None = None
    # Entered session times (HH:MM). When set they take precedence over the
    # meeting window above, on the meeting's date, exactly like /generate.
    start_time: time | None = None
    end_time: time | None = None
    # When set, attendance uses full Zoom segments (same as generate).
    zoom_path: str | None = None


class MatchEntry(BaseModel):
    """One match outcome serialised for the API response."""

    kind: Literal["success", "ambiguous", "not_found"]
    qualtrics_name: str
    zoom_name: str | None = None
    confidence: float | None = None
    # True for a partial (below 1.0) match: it is excluded from generation
    # until someone confirms it (the UI sends it back as an override).
    needs_review: bool = False
    candidates: list[str] | None = None
    attendance: dict[str, object] | None = None
    # Positions in the request's ``ce_requests`` that belong to this person
    # (one person can ask for several CE types). Two different people who
    # share a name get separate entries.
    request_indices: list[int] = []
    email: str | None = None


class MatchResponse(BaseModel):
    """Response for ``POST /api/match``."""

    matches: list[MatchEntry]
    # Notes for the reviewer, such as the Zoom meeting ending before the
    # entered session end.
    warnings: list[str] = []


class PreviewRequest(BaseModel):
    """Body for ``POST /api/preview`` — all fields needed for a certificate."""

    full_name: str
    ce_type: str
    ce_credits: CECredits
    training_title: str
    training_date: date
    instructor_name: str
    license_number: str | None = None
    issue_date: date | None = None
    is_virtual: bool = True
    location: str | None = None
    end_date: date | None = None
    start_time: time | None = None
    end_time: time | None = None


class GenerateRequest(BaseModel):
    """Body for ``POST /api/generate`` — mirrors ``run_pipeline`` parameters."""

    zoom_path: str
    qualtrics_path: str
    title: str
    training_date: date
    instructor: str
    ce_credits: CECredits
    ce_types: list[str]
    start_time: time
    end_time: time
    overrides: dict[str, str] | None = None
    overrides_path: str | None = None
    output_dir: str = "./output"
    excluded_names: list[str] | None = None
    is_virtual: bool = True
    location: str | None = None
    end_date: date | None = None


class DownloadZipRequest(BaseModel):
    """Body for ``POST /api/download-zip``."""

    pdf_paths: list[str]


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════


def _participant_from_brief(brief: MatchParticipantBrief) -> ParticipantAttendance:
    record = AttendanceRecord(
        name_raw=brief.name,
        email=None,
        join_time=brief.first_join,
        leave_time=brief.last_leave,
        duration_minutes=brief.total_attended_minutes,
        is_guest=False,
        is_waiting_room=False,
    )
    return ParticipantAttendance.from_records([record])


def _attendance_payload(
    participant: ParticipantAttendance,
    session_start: datetime,
    session_end: datetime,
) -> dict[str, object]:
    result = validate_attendance(participant, session_start, session_end)
    return {
        "is_eligible": result.is_eligible,
        "late_join": result.late_join_minutes,
        "early_leave": result.early_leave_minutes,
        "gaps": result.mid_session_gaps_minutes,
        "total_missed": result.total_missed_minutes,
        "total_attended": result.total_attended_minutes,
        "failure_reason": result.failure_reason,
    }


def _result_status(status: str) -> str:
    match status:
        case "not_found_in_attendance":
            return "Not Found"
        case "attendance_insufficient":
            return "Attendance"
        case "name_match_ambiguous":
            return "Ambiguous"
        case "needs_review":
            return "Needs Review"
        case "excluded":
            return "Excluded"
        case "ce_type_not_offered":
            return "Not Offered"
        case "duplicate_submission":
            return "Duplicate"
        case "eligible" | _:
            return "Eligible" if status == "eligible" else "Attendance"


def _register_generated_file(path: Path) -> str:
    resolved = path.resolve()
    if (
        resolved.suffix.lower() not in _ALLOWED_CERT_SUFFIXES
        or not resolved.exists()
        or not resolved.is_file()
    ):
        raise HTTPException(status_code=500, detail="Generated certificate file missing")
    token = secrets.token_urlsafe(24)
    _GENERATED_FILES[token] = resolved
    return token


def _registered_file(token: str) -> Path:
    file_path = _GENERATED_FILES.get(token)
    if file_path is None or not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Certificate file not found")
    return file_path


def _clear_generated_registry() -> None:
    _GENERATED_FILES.clear()


# ═══════════════════════════════════════════════════════════════════════════
# Endpoints
# ═══════════════════════════════════════════════════════════════════════════


def _unreadable(exc: UnreadableFileError) -> HTTPException:
    """400 for a file that is not a readable spreadsheet (same wording as before)."""
    return HTTPException(status_code=400, detail=f"Could not read spreadsheet: {exc}")


@router.post("/parse", response_model=ParseResponse)
async def parse_endpoint(request: ParseRequest) -> ParseResponse:
    """Parse Zoom attendance and Qualtrics CE-request reports.

    Returns session metadata, participant summaries, and CE-request
    summaries as JSON.  All file reads run off the event loop via
    ``asyncio.to_thread``.
    """
    try:
        zoom_session = await asyncio.to_thread(
            parse_zoom_attendance, request.zoom_path,
        )
        ce_requests_raw = dedupe_requests(
            await asyncio.to_thread(parse_qualtrics_export, request.qualtrics_path),
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ZoomParseError as exc:
        if isinstance(exc.__cause__, UnreadableFileError):
            raise _unreadable(exc.__cause__) from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except UnreadableFileError as exc:
        raise _unreadable(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except zipfile.BadZipFile as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Could not read spreadsheet: {exc}",
        ) from exc

    participants = [
        ParseParticipant(
            name_raw=p.name_raw,
            first_join=p.first_join.isoformat(),
            last_leave=p.last_leave.isoformat(),
            total_attended_minutes=int(p.total_attended_minutes),
            segment_count=len(p.segments),
        )
        for p in zoom_session.participants
    ]

    ce_requests = [
        ParseCERequest(
            name_on_certificate=req.name_on_certificate,
            email=req.email,
            ce_type=str(req.ce_type),
            license_number=req.license_number,
        )
        for req in ce_requests_raw
    ]

    return ParseResponse(
        session_start=zoom_session.session_start.isoformat(),
        session_end=zoom_session.session_end.isoformat(),
        participants=participants,
        ce_requests=ce_requests,
        participant_count=len(participants),
        request_count=len(ce_requests),
        zoom_host=zoom_session.host,
    )


@router.post("/match", response_model=MatchResponse)
async def match_endpoint(request: MatchRequest) -> MatchResponse:
    """Match Qualtrics CE-request names to Zoom participant names.

    Runs the four-strategy name-matching pipeline (manual override →
    exact normalized → token-set subset → first-name partial) and returns
    a match entry per Qualtrics name with a kind discriminator.

    When ``zoom_path`` is provided, attendance validation uses the full
    multi-segment Zoom parse (same fidelity as ``/api/generate``).
    """
    if not request.ce_requests:
        raise HTTPException(status_code=400, detail="ce_requests must not be empty")

    if request.zoom_path:
        try:
            zoom_session = await asyncio.to_thread(
                parse_zoom_attendance, request.zoom_path,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ZoomParseError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        participants = list(zoom_session.participants)
        session_start = request.session_start or zoom_session.session_start
        session_end = request.session_end or zoom_session.session_end
    else:
        if not request.zoom_participants:
            raise HTTPException(
                status_code=400,
                detail="zoom_participants must not be empty when zoom_path is omitted",
            )
        participants = [_participant_from_brief(p) for p in request.zoom_participants]
        session_start = request.session_start or min(p.first_join for p in participants)
        session_end = request.session_end or max(p.last_leave for p in participants)
    # The Zoom meeting window is real when it comes from the file or the UI;
    # a window guessed from participant join times is not clipped against.
    session_start, session_end, window_warning = judged_window(
        session_start,
        session_end,
        request.start_time,
        request.end_time,
        clip_to_meeting=bool(request.zoom_path or (request.session_start and request.session_end)),
    )

    zoom_lookup: dict[str, ParticipantAttendance] = {}
    for p in participants:
        zoom_lookup.setdefault(p.name_raw, p)
    pairs = [(r.name_on_certificate, r.email) for r in request.ce_requests]

    results = await asyncio.to_thread(
        lambda: match_requests(
            list(zoom_lookup),
            pairs,
            request.overrides,
            zoom_emails={name: p.email for name, p in zoom_lookup.items()},
        ),
    )

    # One entry per person: requests from the same person share one match.
    people: dict[int, list[int]] = {}
    for index, pid in enumerate(person_groups(pairs)):
        people.setdefault(pid, []).append(index)

    entries: list[MatchEntry] = []
    for indices in people.values():
        first = indices[0]
        q_name = pairs[first][0]
        email = next((pairs[i][1] for i in indices if pairs[i][1]), None)
        match_result = results[first]
        match match_result:
            case MatchSuccess(matched_name=matched, confidence=conf):
                participant = zoom_lookup.get(matched)
                entries.append(
                    MatchEntry(
                        kind="success",
                        qualtrics_name=q_name,
                        zoom_name=matched,
                        confidence=conf,
                        needs_review=conf < CONFIRMED_CONFIDENCE,
                        attendance=(
                            _attendance_payload(participant, session_start, session_end)
                            if participant is not None
                            else None
                        ),
                        request_indices=indices,
                        email=email,
                    )
                )
            case MatchAmbiguous(candidates=cands):
                entries.append(
                    MatchEntry(
                        kind="ambiguous",
                        qualtrics_name=q_name,
                        candidates=list(cands),
                        request_indices=indices,
                        email=email,
                    )
                )
            case MatchNotFound():
                entries.append(
                    MatchEntry(
                        kind="not_found",
                        qualtrics_name=q_name,
                        request_indices=indices,
                        email=email,
                    )
                )
            case _:
                assert_never(match_result)

    return MatchResponse(matches=entries, warnings=[window_warning] if window_warning else [])


PREVIEW_WARNINGS_HEADER = "X-Certificate-Warnings"
"""Response header carrying a JSON list of preview warnings, when any."""


@router.post("/preview")
async def preview_endpoint(request: PreviewRequest) -> StreamingResponse:
    """Generate a single certificate preview from the official Word template.

    Returns a PDF when conversion succeeds; otherwise returns the filled
    ``.docx`` (soft-fail) so preview never hard-depends on a converter.
    """
    # Local date, same as /generate and the CLI (a UTC date is a day ahead
    # for evening sessions in the US).
    issue_date = request.issue_date or date.today()  # noqa: DTZ011

    file_bytes, media_type, filename, warnings = await asyncio.to_thread(
        _build_preview_certificate,
        request,
        issue_date,
    )

    headers = {"Content-Disposition": f"inline; filename={filename}"}
    if warnings:
        # ASCII-only JSON so names in any script survive the HTTP header.
        headers[PREVIEW_WARNINGS_HEADER] = json.dumps(warnings, ensure_ascii=True)
    return StreamingResponse(io.BytesIO(file_bytes), media_type=media_type, headers=headers)


def _build_preview_certificate(
    request: PreviewRequest,
    issue_date: date,
) -> tuple[bytes, str, str, list[str]]:
    output = CertificateOutput(
        full_name=request.full_name,
        ce_type=CEType(request.ce_type),
        ce_credits=request.ce_credits,
        training_title=request.training_title,
        training_date=request.training_date,
        instructor_name=request.instructor_name,
        license_number=request.license_number,
        issue_date=issue_date,
    )
    options = CertificateRenderOptions(
        is_virtual=request.is_virtual,
        location=request.location,
        end_date=request.end_date,
        session_start=request.start_time,
        session_end=request.end_time,
    )
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(generate_certificate(output, tmp, options=options))
        data = path.read_bytes()
        warnings = certificate_warnings(output, str(path))
        if path.suffix.lower() == ".pdf":
            return data, "application/pdf", path.name, warnings
        return (
            data,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            path.name,
            warnings,
        )


@router.post("/generate")
async def generate_endpoint(request: GenerateRequest) -> dict[str, object]:
    """Run the full CE certificate generation pipeline.

    Returns a JSON payload with certificates and ineligibility entries.
    Pipeline failures surface as HTTP 400 with ``detail`` set to the error
    messages (previous SSE ``complete``-with-empty-lists behaviour removed).
    """
    _validate_output_dir(request.output_dir)

    result: PipelineResult = await asyncio.to_thread(
        run_pipeline,
        request.zoom_path,
        request.qualtrics_path,
        request.title,
        request.training_date,
        request.instructor,
        request.ce_credits,
        request.ce_types,
        request.start_time,
        request.end_time,
        overrides=request.overrides,
        overrides_path=request.overrides_path,
        output_dir=request.output_dir,
        excluded_names=set(request.excluded_names or []),
        is_virtual=request.is_virtual,
        location=request.location,
        end_date=request.end_date,
    )

    if result.errors:
        raise HTTPException(
            status_code=400,
            detail="; ".join(result.errors),
        )

    _clear_generated_registry()
    if len(result.eligible) != len(result.generated_paths):
        raise HTTPException(
            status_code=500,
            detail=(
                f"Certificate path count mismatch: "
                f"{len(result.eligible)} eligible vs "
                f"{len(result.generated_paths)} paths"
            ),
        )

    certificates: list[dict[str, object]] = []
    for cert, generated_path in zip(
        result.eligible,
        result.generated_paths,
        strict=True,
    ):
        file_path = Path(generated_path)
        if not file_path.is_file():
            raise HTTPException(
                status_code=500,
                detail=f"Generated certificate missing: {file_path.name}",
            )
        certificates.append(
            {
                "name": cert.full_name,
                "ce_type": str(cert.ce_type),
                "filename": file_path.name,
                "path": _register_generated_file(file_path),
            }
        )
    ineligible_entries = [
        {
            "name": entry.name_qualtrics,
            "status": _result_status(str(entry.status)),
            "reason": entry.reason,
        }
        for entry in result.ineligible
    ]
    return {
        "certificates": certificates,
        "ineligible": ineligible_entries,
        "conversion_warning": any(
            Path(p).suffix.lower() == ".docx" for p in result.generated_paths
        ),
        "warnings": result.warnings,
    }


def _validate_output_dir(output_dir: str) -> None:
    """Reject path values that could break AppleScript / shell interpolation."""
    if not output_dir or not output_dir.strip():
        raise HTTPException(status_code=400, detail="output_dir is required")
    if any(ch in output_dir for ch in ('"', "\n", "\r", "\x00")):
        raise HTTPException(
            status_code=400,
            detail="output_dir contains disallowed characters",
        )


@router.post("/download-zip")
async def download_zip_endpoint(request: DownloadZipRequest) -> StreamingResponse:
    """Bundle one or more PDF files into an in-memory ZIP archive.

    Returns the ZIP as a streaming ``application/zip`` response.
    Missing or non-file paths are silently skipped.
    """
    if not request.pdf_paths:
        raise HTTPException(status_code=400, detail="pdf_paths must not be empty")

    def _create_zip() -> io.BytesIO:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for token in request.pdf_paths:
                pdf_path = _registered_file(token)
                zf.write(pdf_path, pdf_path.name)
        _ = buf.seek(0)
        return buf

    zip_buf = await asyncio.to_thread(_create_zip)
    return StreamingResponse(
        zip_buf,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=certificates.zip"},
    )


@router.get("/pdf")
def pdf_endpoint(path: str) -> FileResponse:
    """Return a registered generated certificate file by opaque token."""
    file_path = _registered_file(path)
    suffix = file_path.suffix.lower()
    media = (
        "application/pdf"
        if suffix == ".pdf"
        else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    return FileResponse(file_path, media_type=media)
