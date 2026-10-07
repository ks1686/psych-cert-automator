"""Tests for the Qualtrics CE request export parser."""

from __future__ import annotations

from pathlib import Path

import pytest
from openpyxl import Workbook
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


def test_dropdown_export_keeps_license_number(tmp_path: Path) -> None:
    """The GSAPP export puts the NY license in its own text column."""
    path = tmp_path / "qualtrics.xlsx"
    book = Workbook()
    sheet = book.active
    sheet.append(
        [
            "Name (as you would like it to appear on your CE certificate):",
            "Preferred email address:",
            "Type of CE credit needed: - Selected Choice",
            "Type of CE credit needed: - Psychologist (New York) (please enter license #) - Text",
        ]
    )
    sheet.append(
        [
            "Riley Okonkwo",
            "riley.okonkwo@example.com",
            "Psychologist (New York)",
            "012345",
        ]
    )
    book.save(path)
    book.close()

    requests = parse_qualtrics_export(str(path))
    assert len(requests) == 1
    assert requests[0].license_number == "012345"
