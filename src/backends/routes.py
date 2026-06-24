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
import zipfile
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import TYPE_CHECKING, assert_never

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from fpdf import FPDF
from pydantic import BaseModel

from src.matcher.name_matcher import match_participants
from src.models.certificate import (
    MatchAmbiguous,
    MatchNotFound,
    MatchSuccess,
)
from src.parser.qualtrics import parse_qualtrics_export
from src.parser.zoom import ZoomParseError, parse_zoom_attendance
from src.pipeline import PipelineResult, run_pipeline

router = APIRouter()


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

    name_raw: str


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


class MatchEntry(BaseModel):
    """One match outcome serialised for the API response."""

    qualtrics_name: str
    ce_type: str
    match_kind: str  # "success" | "ambiguous" | "not_found"
    matched_name: str | None = None
    confidence: float | None = None
    candidates: list[str] | None = None


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


def _serialize_pipeline_result(result: PipelineResult) -> dict[str, object]:
    """Convert a ``PipelineResult`` into a JSON-safe dictionary."""
    eligible: list[dict[str, object]] = [
        {
            "full_name": c.full_name,
            "ce_type": str(c.ce_type),
            "ce_credits": c.ce_credits,
            "training_title": c.training_title,
            "training_date": c.training_date.isoformat(),
            "instructor_name": c.instructor_name,
            "license_number": c.license_number,
            "issue_date": c.issue_date.isoformat(),
            "filename": c.output_filename,
        }
        for c in result.eligible
    ]

    ineligible: list[dict[str, object]] = [
        {
            "name_qualtrics": e.name_qualtrics,
            "name_zoom": e.name_zoom,
            "match_status": e.match_status,
            "reason": e.reason,
            "status": str(e.status),
            "late_join_minutes": e.late_join_minutes,
            "early_leave_minutes": e.early_leave_minutes,
            "total_gaps_minutes": e.total_gaps_minutes,
        }
        for e in result.ineligible
    ]

    return {
        "total_requests": result.total_requests,
        "eligible_count": len(eligible),
        "ineligible_count": len(ineligible),
        "errors": result.errors,
        "eligible": eligible,
        "ineligible": ineligible,
    }


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

    zoom_names = [p.name_raw for p in request.zoom_participants]
    qualtrics_names = [r.name_on_certificate for r in request.ce_requests]
    ce_type_map = {r.name_on_certificate: r.ce_type for r in request.ce_requests}

    result = await asyncio.to_thread(
        match_participants, zoom_names, qualtrics_names, request.overrides,
    )

    entries: list[MatchEntry] = []
    for q_name, match_result in result.items():
        ce_type = ce_type_map.get(q_name, "unknown")
        match match_result:
            case MatchSuccess(matched_name=matched, confidence=conf):
                entries.append(
                    MatchEntry(
                        qualtrics_name=q_name,
                        ce_type=ce_type,
                        match_kind="success",
                        matched_name=matched,
                        confidence=conf,
                    )
                )
            case MatchAmbiguous(candidates=cands):
                entries.append(
                    MatchEntry(
                        qualtrics_name=q_name,
                        ce_type=ce_type,
                        match_kind="ambiguous",
                        candidates=list(cands),
                    )
                )
            case MatchNotFound():
                entries.append(
                    MatchEntry(
                        qualtrics_name=q_name,
                        ce_type=ce_type,
                        match_kind="not_found",
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
            {"event": "started", "message": "Pipeline started — parsing reports…"}
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
            overrides_path=request.overrides_path,
            output_dir=request.output_dir,
        )

        payload = _serialize_pipeline_result(result)
        payload["event"] = "complete"
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
            for path_str in request.pdf_paths:
                p = Path(path_str)
                if p.exists() and p.is_file():
                    zf.write(p, p.name)
        buf.seek(0)
        return buf

    zip_buf = await asyncio.to_thread(_create_zip)
    return StreamingResponse(
        zip_buf,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=certificates.zip"},
    )
