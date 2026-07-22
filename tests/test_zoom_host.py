"""Tests for Zoom host metadata extraction (cross-platform path handling)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.generator.zoom_host import extract_zoom_host, host_matches_name


def test_extract_zoom_host_from_sample() -> None:
    sample = Path("input/Zoom Attendance Report Arnoff 3.20.26.xlsx")
    if not sample.is_file():
        pytest.skip("sample Zoom report not present")
    host = extract_zoom_host(str(sample))
    assert host is not None
    assert "Jessica Benas" in host
    assert "@" not in host


def test_host_matches_name() -> None:
    assert host_matches_name("Jessica Benas", "Jessica Benas")
    assert host_matches_name("Jessica Benas", "jessica benas")
    assert not host_matches_name("Jessica Benas", "Alexandra Dillon")
    assert not host_matches_name(None, "Jessica Benas")
