"""The local API requires the per-launch token, and /shutdown needs a JSON body."""

from __future__ import annotations

import asyncio
import json

import pytest
from src.backends import main

TOKEN = "t0ken-for-tests"  # noqa: S105 (test fixture value)


def _call(
    method: str,
    path: str,
    *,
    headers: dict[str, str] | None = None,
    query: str = "",
    body: bytes = b"",
) -> tuple[int, bytes]:
    """Send one request straight into the ASGI app (no network, no httpx)."""
    raw_headers = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": query.encode(),
        "root_path": "",
        "headers": raw_headers,
        "client": ("127.0.0.1", 50000),
        "server": ("127.0.0.1", 8008),
    }
    sent = False
    status = 0
    chunks: list[bytes] = []

    async def receive() -> dict[str, object]:
        nonlocal sent
        if sent:
            await asyncio.sleep(3600)
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message: dict[str, object]) -> None:
        nonlocal status
        if message["type"] == "http.response.start":
            status = int(message["status"])  # type: ignore[arg-type]
        elif message["type"] == "http.response.body":
            chunks.append(message.get("body", b""))  # type: ignore[arg-type]

    asyncio.run(main.app(scope, receive, send))
    return status, b"".join(chunks)


@pytest.fixture
def token(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setattr(main, "API_TOKEN", TOKEN)
    return TOKEN


@pytest.fixture
def no_kill(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    killed: list[int] = []
    monkeypatch.setattr(main.os, "kill", lambda pid, _sig: killed.append(pid))
    return killed


def test_requests_without_the_token_are_rejected(token: str) -> None:
    status, _ = _call("GET", "/health")
    assert status == 401
    status, _ = _call("GET", "/health", headers={"X-Psych-Cert-Token": "wrong"})
    assert status == 401
    status, _ = _call(
        "POST",
        "/api/parse",
        headers={"Content-Type": "application/json"},
        body=b'{"zoom_path": "a", "qualtrics_path": "b"}',
    )
    assert status == 401


def test_requests_with_the_token_are_served(token: str) -> None:
    status, body = _call("GET", "/health", headers={"X-Psych-Cert-Token": token})
    assert status == 200
    assert json.loads(body)["status"] == "healthy"


def test_pdf_links_need_no_launch_token(token: str) -> None:
    """The opaque per-file path token is the capability; no launch token in URLs."""
    status, _ = _call("GET", "/api/pdf", query="path=nope")
    assert status == 404


def test_launch_token_is_not_accepted_in_the_query(token: str) -> None:
    status, _ = _call("GET", "/health", query=f"auth={token}")
    assert status == 401


def test_only_get_pdf_is_exempt(token: str) -> None:
    status, _ = _call("POST", "/api/pdf", query="path=nope")
    assert status == 401


def test_cors_preflight_is_not_blocked(token: str) -> None:
    status, _ = _call(
        "OPTIONS",
        "/api/parse",
        headers={
            "Origin": "tauri://localhost",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-psych-cert-token",
        },
    )
    assert status == 200


def test_shutdown_requires_a_json_body(token: str, no_kill: list[int]) -> None:
    auth = {"X-Psych-Cert-Token": token}
    status, _ = _call("POST", "/shutdown", headers=auth)
    assert status == 422
    status, _ = _call(
        "POST", "/shutdown", headers={**auth, "Content-Type": "text/plain"}, body=b"x"
    )
    assert status == 422
    assert no_kill == []
    status, _ = _call(
        "POST",
        "/shutdown",
        headers={**auth, "Content-Type": "application/json"},
        body=b'{"reason": "app-exit"}',
    )
    assert status == 200
    assert len(no_kill) == 1


def test_port_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PSYCH_CERT_PORT", "51234")
    assert main.configured_port() == 51234
    monkeypatch.delenv("PSYCH_CERT_PORT")
    monkeypatch.delenv("PORT", raising=False)
    assert main.configured_port() == 8008


def test_ui_can_read_the_preview_warnings_header() -> None:
    cors = next(m for m in main.app.user_middleware if "CORS" in str(m.cls))
    assert "X-Certificate-Warnings" in cors.kwargs["expose_headers"]


def test_shutdown_rejects_json_sent_without_a_content_type(token: str, no_kill: list[int]) -> None:
    """A cross-site page cannot shut the backend down with a headerless POST.

    Browsers can send a JSON body without a JSON content type; FastAPI must
    not parse it into the shutdown model.
    """
    status, _ = _call(
        "POST",
        "/shutdown",
        headers={"X-Psych-Cert-Token": token},
        body=b'{"reason": "attack"}',
    )
    assert status == 422
    assert no_kill == []
