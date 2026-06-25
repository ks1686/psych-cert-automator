"""API routes for the CE certificate generation pipeline.

Five endpoints wrapping the existing pipeline, parser, matcher, and generator:

    POST /api/parse        — parse Zoom + Qualtrics reports
    POST /api/match        — match Qualtrics names to Zoom participants
    POST /api/preview      — generate a single PDF preview in memory
    POST /api/generate     — run the full pipeline (SSE progress)
    POST /api/download-zip — bundle PDF files into a ZIP archive
"""

from __future__ import annotations

import asyncio
import io
import json
import secrets
import zipfile
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import TYPE_CHECKING, assert_never

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fpdf import FPDF
from pydantic import BaseModel

from src.matcher.name_matcher import match_participants
from src.models.certificate import (
    MatchAmbiguous,
    MatchNotFound,
    MatchSuccess,
)
from src.models.participant import AttendanceRecord, ParticipantAttendance
from src.parser.qualtrics import parse_qualtrics_export
from src.parser.zoom import ZoomParseError, parse_zoom_attendance
from src.pipeline import PipelineResult, run_pipeline
from src.validator.attendance import validate_attendance

router = APIRouter()
_GENERATED_PDFS: dict[str, Path] = {}


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


class MatchEntry(BaseModel):
    """One match outcome serialised for the API response."""

    kind: str  # "success" | "ambiguous" | "not_found"
    qualtrics_name: str
    zoom_name: str | None = None
    confidence: float | None = None
    candidates: list[str] | None = None
    attendance: dict[str, object] | None = None


class MatchResponse(BaseModel):
    """Response for ``POST /api/match``."""

    matches: list[MatchEntry]


class PreviewRequest(BaseModel):
    """Body for ``POST /api/preview`` — all fields needed for a certificate."""

    full_name: str
    ce_type: str
    ce_credits: int
    training_title: str
    training_date: date
    instructor_name: str
    license_number: str | None = None
    issue_date: date | None = None


class GenerateRequest(BaseModel):
    """Body for ``POST /api/generate`` — mirrors ``run_pipeline`` parameters."""

    zoom_path: str
    qualtrics_path: str
    title: str
    training_date: date
    instructor: str
    ce_credits: int
    ce_types: list[str]
    start_time: time
    end_time: time
    overrides: dict[str, str] | None = None
    overrides_path: str | None = None
    output_dir: str = "./output"


class DownloadZipRequest(BaseModel):
    """Body for ``POST /api/download-zip``."""

    pdf_paths: list[str]


# ═══════════════════════════════════════════════════════════════════════════
# Preview PDF layout helpers (inlined from src/generator/certificate.py)
# ═══════════════════════════════════════════════════════════════════════════

_PAGE_W, _PAGE_H = 279.4, 215.9  # Letter landscape (mm)
_PV_MARGIN = 15.0
_PV_BORDER_INSET = 8.0
_PV_INNER_W = _PAGE_W - 2 * _PV_MARGIN
_PV_INNER_H = _PAGE_H - 2 * _PV_MARGIN
_PV_BORDER_W = _PAGE_W - 2 * _PV_BORDER_INSET
_PV_BORDER_H = _PAGE_H - 2 * _PV_BORDER_INSET

_PV_FONT_TITLE = ("Helvetica", "B", 26)
_PV_FONT_NAME = ("Helvetica", "B", 22)
_PV_FONT_BODY = ("Helvetica", "", 14)
_PV_FONT_DETAIL = ("Helvetica", "", 12)
_PV_FONT_SIGNATURE = ("Helvetica", "", 11)


def _preview_format_date(d: date) -> str:
    """Format a date like 'March 20, 2026' (no leading zero on day)."""
    return f"{d:%B} {d.day}, {d.year}"


def _preview_text_line(
    pdf: FPDF, text: str, family: str, style: str, size: int
) -> None:
    """Draw a centered line of text and advance Y."""
    pdf.set_font(family, style, size)
    _ = pdf.cell(_PV_INNER_W, 8, text, align="C", new_x="LMARGIN", new_y="NEXT")


def _preview_vspace(pdf: FPDF, mm: float) -> None:
    """Add vertical space."""
    pdf.ln(mm)


def _preview_draw_border(pdf: FPDF) -> None:
    """Draw a double-line decorative border."""
    pdf.set_line_width(0.4)
    pdf.rect(_PV_BORDER_INSET, _PV_BORDER_INSET, _PV_BORDER_W, _PV_BORDER_H)
    pdf.set_line_width(0.2)
    inset2 = _PV_BORDER_INSET + 2
    pdf.rect(inset2, inset2, _PV_BORDER_W - 4, _PV_BORDER_H - 4)


def _preview_draw_signature_block(pdf: FPDF) -> None:
    """Draw instructor signature line and date on the same row."""
    y_sig = pdf.get_y() + 12
    left_x = _PV_MARGIN + 20
    right_x = _PV_MARGIN + _PV_INNER_W - 80

    pdf.set_font(*_PV_FONT_SIGNATURE)
    _ = pdf.line(left_x, y_sig, left_x + 70, y_sig)
    _ = pdf.set_xy(left_x, y_sig + 2)
    _ = pdf.cell(70, 5, "Instructor Signature", align="C")

    _ = pdf.line(right_x, y_sig, right_x + 60, y_sig)
    _ = pdf.set_xy(right_x, y_sig + 2)
    _ = pdf.cell(60, 5, "Date", align="C")


def _build_preview_pdf(  # noqa: PLR0913
    full_name: str,
    ce_type: str,
    ce_credits: int,
    training_title: str,
    training_date: date,
    instructor_name: str,
    license_number: str | None,
    issue_date: date,
) -> bytes:
    """Generate a single certificate PDF in memory (no file write).

    Replicates the layout from ``src/generator/certificate.py`` so the
    preview is pixel-identical to the final generated certificate.
    """
    pdf = FPDF(orientation="L", unit="mm", format="Letter")
    pdf.set_auto_page_break(auto=False)
    pdf.add_page()

    _preview_draw_border(pdf)
    _preview_vspace(pdf, 8)

    _preview_text_line(pdf, "Certificate of Completion", *_PV_FONT_TITLE)
    _preview_vspace(pdf, 2)
    _ = pdf.set_draw_color(0)
    _ = pdf.set_line_width(0.3)
    mid_x = _PV_MARGIN + _PV_INNER_W / 2
    _ = pdf.line(mid_x - 40, pdf.get_y(), mid_x + 40, pdf.get_y())
    _preview_vspace(pdf, 6)

    _preview_text_line(pdf, "This certifies that", *_PV_FONT_BODY)
    _preview_vspace(pdf, 4)

    _preview_text_line(pdf, full_name, *_PV_FONT_NAME)
    _preview_vspace(pdf, 4)

    credits_text = (
        f"has successfully completed {ce_credits}"
        + " Continuing Education credit hour"
        + ("s" if ce_credits != 1 else "")
        + f" in {ce_type}"
    )
    _preview_text_line(pdf, credits_text, *_PV_FONT_BODY)
    _preview_vspace(pdf, 8)

    _preview_text_line(pdf, f"Training:  {training_title}", *_PV_FONT_DETAIL)
    _preview_vspace(pdf, 2)
    _preview_text_line(
        pdf, f"Date:  {_preview_format_date(training_date)}", *_PV_FONT_DETAIL
    )
    _preview_vspace(pdf, 2)
    _preview_text_line(
        pdf, f"Instructor:  {instructor_name}", *_PV_FONT_DETAIL
    )

    if license_number:
        _preview_vspace(pdf, 2)
        _preview_text_line(
            pdf,
            f"License / Certificate #:  {license_number}",
            *_PV_FONT_DETAIL,
        )

    _preview_vspace(pdf, 4)
    _preview_text_line(
        pdf, f"Issued:  {_preview_format_date(issue_date)}", *_PV_FONT_DETAIL
    )

    _preview_draw_signature_block(pdf)

    return bytes(pdf.output())


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
        case "eligible":
            return "Attendance"
        case _:
            return "Attendance"


def _register_generated_pdf(path: Path) -> str:
    resolved = path.resolve()
    if resolved.suffix.lower() != ".pdf" or not resolved.exists() or not resolved.is_file():
        raise HTTPException(status_code=500, detail="Generated PDF missing")
    token = secrets.token_urlsafe(24)
    _GENERATED_PDFS[token] = resolved
    return token


def _registered_pdf(token: str) -> Path:
    pdf_path = _GENERATED_PDFS.get(token)
    if pdf_path is None or not pdf_path.exists() or not pdf_path.is_file():
        raise HTTPException(status_code=404, detail="PDF not found")
    return pdf_path


# ═══════════════════════════════════════════════════════════════════════════
# Endpoints
# ═══════════════════════════════════════════════════════════════════════════


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
        ce_requests_raw = await asyncio.to_thread(
            parse_qualtrics_export, request.qualtrics_path,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ZoomParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

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
    )


@router.post("/match", response_model=MatchResponse)
async def match_endpoint(request: MatchRequest) -> MatchResponse:
    """Match Qualtrics CE-request names to Zoom participant names.

    Runs the four-strategy name-matching pipeline (manual override →
    exact normalized → token-set subset → first-name partial) and returns
    a match entry per Qualtrics name with a kind discriminator.
    """
    if not request.zoom_participants:
        raise HTTPException(status_code=400, detail="zoom_participants must not be empty")
    if not request.ce_requests:
        raise HTTPException(status_code=400, detail="ce_requests must not be empty")

    participants = [_participant_from_brief(p) for p in request.zoom_participants]
    zoom_names = [p.name_raw for p in participants]
    zoom_lookup = {p.name_raw: p for p in participants}
    qualtrics_names = [r.name_on_certificate for r in request.ce_requests]
    session_start = request.session_start or min(p.first_join for p in participants)
    session_end = request.session_end or max(p.last_leave for p in participants)

    result = await asyncio.to_thread(
        match_participants, zoom_names, qualtrics_names, request.overrides,
    )

    entries: list[MatchEntry] = []
    for q_name, match_result in result.items():
        match match_result:
            case MatchSuccess(matched_name=matched, confidence=conf):
                participant = zoom_lookup[matched]
                entries.append(
                    MatchEntry(
                        kind="success",
                        qualtrics_name=q_name,
                        zoom_name=matched,
                        confidence=conf,
                        attendance=_attendance_payload(
                            participant, session_start, session_end
                        ),
                    )
                )
            case MatchAmbiguous(candidates=cands):
                entries.append(
                    MatchEntry(
                        kind="ambiguous",
                        qualtrics_name=q_name,
                        candidates=list(cands),
                    )
                )
            case MatchNotFound():
                entries.append(
                    MatchEntry(
                        kind="not_found",
                        qualtrics_name=q_name,
                    )
                )
            case _:
                assert_never(match_result)

    return MatchResponse(matches=entries)


@router.post("/preview")
async def preview_endpoint(request: PreviewRequest) -> StreamingResponse:
    """Generate a single certificate PDF in memory and return it.

    Replicates the full certificate layout so the preview is visually
    identical to the final output, but without writing to disk.
    """
    issue_date = request.issue_date or datetime.now(tz=timezone.utc).date()  # noqa: UP017

    pdf_bytes = await asyncio.to_thread(
        _build_preview_pdf,
        request.full_name,
        request.ce_type,
        request.ce_credits,
        request.training_title,
        request.training_date,
        request.instructor_name,
        request.license_number,
        issue_date,
    )

    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": "inline; filename=preview.pdf"},
    )


@router.post("/generate")
async def generate_endpoint(request: GenerateRequest) -> StreamingResponse:
    """Run the full CE certificate generation pipeline with SSE progress.

    Streams Server-Sent Events: a ``started`` event when the pipeline
    begins, then a ``complete`` event carrying counts and summary data
    once ``run_pipeline`` finishes.  All synchronous I/O (Excel parsing,
    PDF generation) runs off the event loop.
    """

    async def event_stream() -> AsyncGenerator[str, None]:
        yield "data: " + json.dumps(
            {
                "type": "progress",
                "current": 0,
                "total": 0,
                "success_count": 0,
                "failure_count": 0,
            }
        ) + "\n\n"

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
        )

        certificates = [
            {
                "name": cert.full_name,
                "ce_type": str(cert.ce_type),
                "filename": cert.output_filename,
                "path": _register_generated_pdf(Path(request.output_dir) / cert.output_filename),
            }
            for cert in result.eligible
        ]
        ineligible_entries = [
            {
                "name": entry.name_qualtrics,
                "status": _result_status(str(entry.status)),
                "reason": entry.reason,
            }
            for entry in result.ineligible
        ]
        payload: dict[str, object] = {
            "type": "complete",
            "certificates": certificates,
            "ineligible": ineligible_entries,
        }
        yield "data: " + json.dumps(payload, default=str) + "\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


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
                pdf_path = _registered_pdf(token)
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
    """Return a registered generated PDF by opaque token."""
    pdf_path = _registered_pdf(path)
    return FileResponse(pdf_path, media_type="application/pdf")
