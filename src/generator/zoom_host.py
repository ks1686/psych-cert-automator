"""Read Zoom meeting host metadata without modifying the Zoom parser module."""

from __future__ import annotations

import re
from pathlib import Path

import openpyxl

from src.parser.zoom import ZoomParseError

_EMAIL_IN_PARENS = re.compile(r"\s*\([^)]*@[^)]*\)\s*")


def extract_zoom_host(filepath: str) -> str | None:
    """Return the Zoom meeting host display name from cell C2, if present.

    Zoom usage reports store the host in row 2, column C as a string like
    ``Jessica Benas (jbenas@rutgers.edu)``. The email parenthetical is stripped
    so the value can be compared to Qualtrics / participant names.
    """
    path = Path(filepath)
    if not path.is_file():
        raise ZoomParseError(filepath=filepath, reason="file not found")

    try:
        workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except Exception as exc:
        raise ZoomParseError(filepath=filepath, reason=f"cannot open workbook: {exc}") from exc

    try:
        worksheet = workbook.active
        if worksheet is None:
            return None
        raw: object = worksheet["C2"].value
    finally:
        workbook.close()

    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    cleaned = _EMAIL_IN_PARENS.sub("", text).strip()
    return cleaned or text


def host_matches_name(host: str | None, candidate: str) -> bool:
    """Return True when ``candidate`` appears to be the Zoom host."""
    if host is None:
        return False
    host_norm = _norm(host)
    cand_norm = _norm(candidate)
    if not host_norm or not cand_norm:
        return False
    return host_norm == cand_norm or host_norm in cand_norm or cand_norm in host_norm


def _norm(value: str) -> str:
    return " ".join(value.casefold().split())
