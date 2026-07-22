"""FastAPI backend scaffold for the certificate generation pipeline.

Provides a health endpoint for Tauri sidecar readiness probing, a
graceful shutdown mechanism (POST endpoint + stdin listener), and
session save/load endpoints for the certificate-generation workflow.
"""

from __future__ import annotations

import json
import os
import re
import signal
import sys
import threading
from pathlib import Path

# Force line-buffered stdout/stderr. Python defaults to full block-buffering
# when stdout isn't a real terminal (e.g. piped by the Tauri sidecar), so
# print()/logging output can sit unflushed indefinitely — invisible to the
# app's live startup log even though the process is running fine.
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from src.backends.routes import router  # noqa: E402
from src.models.session import SessionConfig  # noqa: E402
from src.models.training import TrainingMetadata  # noqa: E402


def _stdin_listener() -> None:
    """Read lines from stdin; trigger graceful shutdown on the sidecar signal."""
    for line in sys.stdin:
        if line == "sidecar shutdown\n":
            os.kill(os.getpid(), signal.SIGINT)
            return


app = FastAPI(title="psych-cert-gen backend")

# Allowed webview origins across platforms. Tauri v2 serves the app from a
# different origin per platform, and getting this wrong silently breaks every
# frontend fetch with a CORS "Failed to fetch":
#   - macOS / iOS / Linux : tauri://localhost   (custom protocol)
#   - Windows / Android    : http://tauri.localhost  (WebView2 requires http)
# "https://tauri.localhost" is included for configs that use HTTPS custom
# protocols, and "http://localhost:1420" is the Vite dev server.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:1420",
        "tauri://localhost",
        "http://tauri.localhost",
        "https://tauri.localhost",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")


@app.get("/health")
async def health() -> dict[str, str | int]:
    """Return liveness status and server PID."""
    return {"status": "healthy", "pid": os.getpid()}


@app.post("/shutdown")
async def shutdown() -> dict[str, str]:
    """Trigger graceful shutdown via SIGINT."""
    os.kill(os.getpid(), signal.SIGINT)
    return {"status": "shutting_down"}


SESSIONS_DIR = Path.home() / ".psych-cert-gen" / "sessions"


class _SessionRequest(BaseModel):
    title: str
    date: str
    instructor: str
    ce_credits: int
    ce_types: str
    start_time: str
    end_time: str
    end_date: str | None = None
    is_multi_day: bool = False
    is_virtual: bool = True
    location: str | None = None


def _slugify(text: str) -> str:
    """Turn a title string into a safe filename slug."""
    slug = text.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[-\s]+", "_", slug)
    return slug[:64]


@app.get("/api/sessions")
async def list_sessions() -> list[dict[str, str | int | bool | None]]:
    """Return metadata for every saved session file."""
    sessions: list[dict[str, str | int | bool | None]] = []
    if not SESSIONS_DIR.exists():
        return sessions
    for session_id, f in enumerate(sorted(SESSIONS_DIR.glob("*.json"))):
        try:
            session = SessionConfig.load(f)
        except (json.JSONDecodeError, OSError, TypeError, ValueError):
            continue
        meta = session.metadata
        sessions.append(
            {
                "id": session_id,
                "title": meta.title,
                "date": meta.date.isoformat(),
                "end_date": meta.end_date.isoformat() if meta.end_date else None,
                "is_multi_day": meta.is_multi_day,
                "instructor": meta.instructor_name,
                "ce_credits": meta.ce_credits,
                "ce_types": ",".join(sorted(meta.ce_types_offered)),
                "start_time": meta.session_start.isoformat(timespec="minutes"),
                "end_time": meta.session_end.isoformat(timespec="minutes"),
                "is_virtual": meta.is_virtual,
                "location": meta.location,
                "name": f.stem,
                "saved_at": session.saved_at.isoformat(),
                "path": str(f),
            }
        )
    return sessions


@app.post("/api/sessions")
async def create_session(session_request: _SessionRequest) -> dict[str, str]:
    """Create and persist a new certificate-generation session."""
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    end_date = session_request.end_date if session_request.is_multi_day else None
    metadata = TrainingMetadata.from_config(
        {
            "title": session_request.title,
            "date": session_request.date,
            "instructor_name": session_request.instructor,
            "ce_credits": session_request.ce_credits,
            "ce_types_offered": [
                ce_type.strip()
                for ce_type in session_request.ce_types.split(",")
                if ce_type.strip()
            ],
            "session_start": session_request.start_time,
            "session_end": session_request.end_time,
            "end_date": end_date,
            "is_virtual": session_request.is_virtual,
            "location": None if session_request.is_virtual else session_request.location,
        }
    )
    session = SessionConfig(metadata=metadata)
    name = _slugify(session.metadata.title)
    path = SESSIONS_DIR / f"{name}.json"
    session.save(path)
    return {
        "name": name,
        "path": str(path),
        "saved_at": session.saved_at.isoformat(),
    }


if __name__ == "__main__":
    import uvicorn

    listener = threading.Thread(target=_stdin_listener, daemon=True)
    listener.start()

    port = int(os.environ.get("PORT", "8008"))
    uvicorn.run(app, host="127.0.0.1", port=port)
