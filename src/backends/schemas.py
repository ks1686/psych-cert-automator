"""Wire-format schemas for the FastAPI boundary.

Canonical request/response models live in ``src.backends.routes`` (they are
tightly coupled to the endpoints). This module re-exports them so callers and
tests have a stable import path without a second divergent definition.
"""

from __future__ import annotations

from src.backends.routes import (
    DownloadZipRequest,
    GenerateRequest,
    MatchCERequestBrief,
    MatchEntry,
    MatchParticipantBrief,
    MatchRequest,
    MatchResponse,
    ParseCERequest,
    ParseParticipant,
    ParseRequest,
    ParseResponse,
    PreviewRequest,
)

__all__ = [
    "DownloadZipRequest",
    "GenerateRequest",
    "MatchCERequestBrief",
    "MatchEntry",
    "MatchParticipantBrief",
    "MatchRequest",
    "MatchResponse",
    "ParseCERequest",
    "ParseParticipant",
    "ParseRequest",
    "ParseResponse",
    "PreviewRequest",
]
