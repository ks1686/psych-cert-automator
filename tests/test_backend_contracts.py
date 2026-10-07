from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING, ClassVar

import pytest
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict
from src.backends.routes import (
    DownloadZipRequest,
    GenerateRequest,
    MatchRequest,
    ParseRequest,
    PreviewRequest,
    download_zip_endpoint,
    generate_endpoint,
    match_endpoint,
    parse_endpoint,
    preview_endpoint,
)

if TYPE_CHECKING:
    from pathlib import Path


class _GeneratedCertificate(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    path: str


class _GenerateResponse(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    certificates: list[_GeneratedCertificate]
    ineligible: list[dict[str, object]]
    conversion_warning: bool


async def _response_body(response: object) -> bytes:
    body_iterator = getattr(response, "body_iterator", None)
    if body_iterator is None:
        raise TypeError("expected StreamingResponse")
    chunks: list[bytes] = []
    async for chunk in body_iterator:
        if isinstance(chunk, str):
            chunks.append(chunk.encode())
        else:
            chunks.append(bytes(chunk))
    return b"".join(chunks)


def test_match_endpoint_accepts_frontend_participant_shape() -> None:
    session_start = datetime(2026, 3, 20, 9, 0, tzinfo=UTC).isoformat()
    session_end = datetime(2026, 3, 20, 12, 0, tzinfo=UTC).isoformat()

    request = MatchRequest.model_validate(
        {
            "session_start": session_start,
            "session_end": session_end,
            "zoom_participants": [
                {
                    "name": "Dr. Alice Jones",
                    "first_join": session_start,
                    "last_leave": session_end,
                    "total_attended_minutes": 180,
                    "segments_count": 1,
                }
            ],
            "ce_requests": [
                {
                    "name_on_certificate": "Alice Jones",
                    "email": "alice@example.com",
                    "ce_type": "APA",
                    "license_number": None,
                }
            ],
        },
    )

    response = asyncio.run(match_endpoint(request))

    assert response.model_dump(mode="json")["matches"] == [
        {
            "kind": "success",
            "qualtrics_name": "Alice Jones",
            "zoom_name": "Dr. Alice Jones",
            "confidence": 0.9,
            "candidates": None,
            "attendance": {
                "is_eligible": True,
                "late_join": 0.0,
                "early_leave": 0.0,
                "gaps": 0.0,
                "total_missed": 0.0,
                "total_attended": 180,
                "failure_reason": None,
            },
        }
    ]


def test_match_with_zoom_path_uses_real_multi_segment_attendance() -> None:
    """Synthetic first_join→last_leave hides mid-session gaps; zoom_path must not."""
    request = MatchRequest.model_validate(
        {
            "zoom_path": "tests/fixtures/sample_zoom.xlsx",
            "zoom_participants": [
                {
                    "name": "Scott Simmons",
                    "first_join": "2026-03-20T08:58:37",
                    "last_leave": "2026-03-20T12:11:13",
                    "total_attended_minutes": 17,
                    "segments_count": 1,  # lied — file has 2 segments
                }
            ],
            "ce_requests": [
                {
                    "name_on_certificate": "Scott Simmons",
                    "email": None,
                    "ce_type": "APA",
                    "license_number": None,
                }
            ],
            "session_start": "2026-03-20T08:47:02",
            "session_end": "2026-03-20T12:11:14",
        },
    )

    response = asyncio.run(match_endpoint(request))
    match = response.matches[0]
    assert match.kind == "success"
    assert match.attendance is not None
    assert match.attendance["is_eligible"] is False
    gaps = match.attendance["gaps"]
    assert isinstance(gaps, (int, float))
    assert gaps > 0  # mid-session gap from real segments


def test_match_without_zoom_path_still_uses_synthetic_brief() -> None:
    """Backward-compat: briefs alone still work (tests / thin clients)."""
    request = MatchRequest.model_validate(
        {
            "zoom_participants": [
                {
                    "name": "Scott Simmons",
                    "first_join": "2026-03-20T08:58:37",
                    "last_leave": "2026-03-20T12:11:13",
                    "total_attended_minutes": 17,
                    "segments_count": 1,
                }
            ],
            "ce_requests": [
                {
                    "name_on_certificate": "Scott Simmons",
                    "email": None,
                    "ce_type": "APA",
                    "license_number": None,
                }
            ],
            "session_start": "2026-03-20T08:47:02",
            "session_end": "2026-03-20T12:11:14",
        },
    )
    response = asyncio.run(match_endpoint(request))
    assert response.matches[0].attendance is not None
    # Synthetic single segment cannot see the mid-session gap.
    gaps = response.matches[0].attendance["gaps"]
    assert isinstance(gaps, (int, float))
    assert gaps == 0.0


def test_preview_endpoint_accepts_flat_frontend_payload() -> None:
    request = PreviewRequest.model_validate(
        {
            "full_name": "Alice Jones",
            "ce_type": "APA",
            "ce_credits": 3,
            "training_title": "Ethics Training",
            "training_date": "2026-03-20",
            "instructor_name": "Dr. Jane Smith",
            "license_number": None,
            "issue_date": "2026-03-21",
        },
    )

    response = asyncio.run(preview_endpoint(request))
    body = asyncio.run(_response_body(response))

    assert response.media_type in {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }
    assert body.startswith(b"%PDF") or body.startswith(b"PK")


def test_download_zip_rejects_unregistered_pdf_paths(tmp_path: Path) -> None:
    pdf_path = tmp_path / "certificate.pdf"
    _ = pdf_path.write_bytes(b"%PDF-1.3\n")

    request = DownloadZipRequest.model_validate({"pdf_paths": [str(pdf_path)]})
    with pytest.raises(HTTPException):
        _ = asyncio.run(download_zip_endpoint(request))


def test_generate_returns_json_and_registers_download_tokens(tmp_path: Path) -> None:
    generate_request = GenerateRequest.model_validate(
        {
            "zoom_path": "tests/fixtures/sample_zoom.xlsx",
            "qualtrics_path": "tests/fixtures/sample_qualtrics.xlsx",
            "title": "Ethics Training",
            "training_date": "2026-03-20",
            "instructor": "Dr. Jane Smith",
            "ce_credits": 3,
            "ce_types": ["APA"],
            "start_time": "08:47",
            "end_time": "12:11",
            "output_dir": str(tmp_path),
        }
    )
    payload = _GenerateResponse.model_validate(
        asyncio.run(generate_endpoint(generate_request)),
    )
    assert len(payload.certificates) >= 1
    token = payload.certificates[0].path

    request = DownloadZipRequest.model_validate({"pdf_paths": [token]})
    response = asyncio.run(download_zip_endpoint(request))
    body = asyncio.run(_response_body(response))

    assert response.media_type == "application/zip"
    assert body.startswith(b"PK")


def test_generate_rejects_bad_paths_with_http_error(tmp_path: Path) -> None:
    generate_request = GenerateRequest.model_validate(
        {
            "zoom_path": str(tmp_path / "missing_zoom.xlsx"),
            "qualtrics_path": "tests/fixtures/sample_qualtrics.xlsx",
            "title": "Ethics Training",
            "training_date": "2026-03-20",
            "instructor": "Dr. Jane Smith",
            "ce_credits": 3,
            "ce_types": ["APA"],
            "start_time": "08:47",
            "end_time": "12:11",
            "output_dir": str(tmp_path),
        }
    )
    with pytest.raises(HTTPException) as exc_info:
        _ = asyncio.run(generate_endpoint(generate_request))
    assert exc_info.value.status_code == 400


def test_generate_rejects_injectable_output_dir(tmp_path: Path) -> None:
    generate_request = GenerateRequest.model_validate(
        {
            "zoom_path": "tests/fixtures/sample_zoom.xlsx",
            "qualtrics_path": "tests/fixtures/sample_qualtrics.xlsx",
            "title": "Ethics Training",
            "training_date": "2026-03-20",
            "instructor": "Dr. Jane Smith",
            "ce_credits": 3,
            "ce_types": ["APA"],
            "start_time": "08:47",
            "end_time": "12:11",
            "output_dir": str(tmp_path) + '" & do shell script "id',
        }
    )
    with pytest.raises(HTTPException) as exc_info:
        _ = asyncio.run(generate_endpoint(generate_request))
    assert exc_info.value.status_code == 400


def test_excluded_status_label() -> None:
    from src.backends.routes import _result_status

    assert _result_status("excluded") == "Excluded"
    assert _result_status("attendance_insufficient") == "Attendance"
    assert _result_status("ce_type_not_offered") == "Not Offered"


def test_parse_endpoint_rejects_a_file_that_is_not_a_workbook(tmp_path: Path) -> None:
    bad = tmp_path / "not-zoom.xlsx"
    bad.write_text("this is not a workbook", encoding="utf-8")
    request = ParseRequest.model_validate(
        {
            "zoom_path": str(bad),
            "qualtrics_path": "tests/fixtures/sample_qualtrics.xlsx",
        },
    )
    with pytest.raises(HTTPException) as exc_info:
        _ = asyncio.run(parse_endpoint(request))
    assert exc_info.value.status_code == 400
    assert "spreadsheet" in str(exc_info.value.detail).lower()


def test_parse_endpoint_returns_host_and_counts() -> None:
    request = ParseRequest.model_validate(
        {
            "zoom_path": "tests/fixtures/sample_zoom.xlsx",
            "qualtrics_path": "tests/fixtures/sample_qualtrics.xlsx",
        },
    )
    response = asyncio.run(parse_endpoint(request))
    assert response.participant_count >= 1
    assert response.request_count >= 1
    assert any(p.name_raw == "Hannah Lee" for p in response.participants)
    assert response.zoom_host is not None
    assert "Jessica Benas" in response.zoom_host
