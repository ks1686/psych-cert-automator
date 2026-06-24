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

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.backends.routes import router
from src.models.session import SessionConfig  # noqa: TC001


def _stdin_listener() -> None:
    """Read lines from stdin; trigger graceful shutdown on the sidecar signal."""
    for line in sys.stdin:
        if line == "sidecar shutdown\n":
            os.kill(os.getpid(), signal.SIGINT)
            return


app = FastAPI(title="psych-cert-gen backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:1420",
        "tauri://localhost",
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


def _slugify(text: str) -> str:
    """Turn a title string into a safe filename slug."""
    slug = text.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[-\s]+", "_", slug)
    return slug[:64]


@app.get("/api/sessions")
async def list_sessions() -> list[dict[str, str]]:
    """Return metadata for every saved session file."""
    sessions: list[dict[str, str]] = []
    if not SESSIONS_DIR.exists():
        return sessions
    for f in sorted(SESSIONS_DIR.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))  # pyright: ignore[reportAny]
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(data, dict):
            continue
        saved_at_raw = data.get("saved_at", "")  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        sessions.append(
            {
                "name": f.stem,
                "saved_at": str(saved_at_raw) if saved_at_raw else "",  # pyright: ignore[reportUnknownArgumentType]
                "path": str(f),
            }
        )
    return sessions


@app.post("/api/sessions")
async def create_session(session: SessionConfig) -> dict[str, str]:
    """Create and persist a new certificate-generation session."""
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
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
