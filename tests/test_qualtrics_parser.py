"""Tests for the Qualtrics CE request export parser."""

from __future__ import annotations

from pathlib import Path

import pytest
from src.parser.qualtrics import parse_qualtrics_export

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE_QUALTRICS = FIXTURES / "sample_qualtrics.xlsx"


def test_parses_sample_file() -> None:
    """Given a valid Qualtrics export, parse_qualtrics_export returns CERequest
    objects with correct CE type mapping."""
    requests = parse_qualtrics_export(str(SAMPLE_QUALTRICS))

    assert len(requests) >= 1

    jessica = [r for r in requests if r.name_on_certificate == "Jessica Benas"]
    assert len(jessica) == 1
    assert jessica[0].ce_type == "Psychologist (APA)"


def test_file_not_found() -> None:
    """Given a non-existent filepath, parse_qualtrics_export raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        _ = parse_qualtrics_export("/nonexistent/path/file.xlsx")


def test_extracts_name_and_email() -> None:
    """Given a sample with name and email columns, those fields are correctly extracted
    for each survey response."""
    requests = parse_qualtrics_export(str(SAMPLE_QUALTRICS))

    jessica = next(r for r in requests if r.name_on_certificate == "Jessica Benas")
    assert jessica.name_on_certificate == "Jessica Benas"
    assert jessica.email == "jbenas@gsapp.rutgers.edu"
