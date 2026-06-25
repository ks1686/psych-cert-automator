from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING, ClassVar, Literal

import pytest
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict
from src.backends.routes import (
    DownloadZipRequest,
    GenerateRequest,
    MatchRequest,
    PreviewRequest,
    download_zip_endpoint,
    generate_endpoint,
    match_endpoint,
    preview_endpoint,
)

if TYPE_CHECKING:
    from pathlib import Path

    from starlette.responses import StreamingResponse


class _GeneratedCertificate(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    path: str


class _GenerateCompleteEvent(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    type: Literal["complete"]
    certificates: list[_GeneratedCertificate]


async def _response_body(response: StreamingResponse) -> bytes:
    chunks: list[bytes] = []
    async for chunk in response.body_iterator:
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

    assert response.media_type == "application/pdf"
    assert body.startswith(b"%PDF")


def test_download_zip_rejects_unregistered_pdf_paths(tmp_path: Path) -> None:
    pdf_path = tmp_path / "certificate.pdf"
    _ = pdf_path.write_bytes(b"%PDF-1.3\n")

    request = DownloadZipRequest.model_validate({"pdf_paths": [str(pdf_path)]})
    with pytest.raises(HTTPException):
        _ = asyncio.run(download_zip_endpoint(request))


def test_download_zip_accepts_registered_pdf_tokens(tmp_path: Path) -> None:
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
    generate_response = asyncio.run(generate_endpoint(generate_request))
    generate_body = asyncio.run(_response_body(generate_response)).decode()
    complete_events = [
        _GenerateCompleteEvent.model_validate_json(line.removeprefix("data: "))
        for line in generate_body.splitlines()
        if line.startswith("data: ") and '"type": "complete"' in line
    ]
    token = complete_events[0].certificates[0].path

    request = DownloadZipRequest.model_validate({"pdf_paths": [token]})
    response = asyncio.run(download_zip_endpoint(request))
    body = asyncio.run(_response_body(response))

    assert response.media_type == "application/zip"
    assert body.startswith(b"PK")
