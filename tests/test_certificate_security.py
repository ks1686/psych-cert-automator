from __future__ import annotations

import zipfile
from datetime import date
from html import unescape
from typing import TYPE_CHECKING

from src.generator.report import generate_ineligibility_report
from src.models.certificate import (
    CertificateOutput,
    EligibilityStatus,
    IneligibilityEntry,
)
from src.models.training import CEType

if TYPE_CHECKING:
    from pathlib import Path


def test_certificate_filename_removes_path_separators() -> None:
    certificate = CertificateOutput(
        full_name="../Alice /../../Jones",
        ce_type=CEType("APA/../../evil"),
        ce_credits=3,
        training_title="Ethics",
        training_date=date(2026, 3, 20),
        instructor_name="Dr. Smith",
        license_number=None,
        issue_date=date(2026, 3, 21),
    )

    assert certificate.output_filename == "Jones_Alice_APA_evil_2026-03-20.pdf"


def _workbook_xml(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        xml_parts = [
            archive.read(name).decode()
            for name in archive.namelist()
            if name.startswith("xl/") and name.endswith(".xml")
        ]
    return unescape("\n".join(xml_parts))


def test_ineligibility_report_escapes_formula_strings(tmp_path: Path) -> None:
    output_path = tmp_path / "report.xlsx"
    entry = IneligibilityEntry(
        name_qualtrics="=cmd|' /C calc'!A0",
        name_zoom="+Zoom Name",
        match_status="-matched",
        late_join_minutes=None,
        early_leave_minutes=None,
        total_gaps_minutes=None,
        rejected_ce_types=("@APA",),
        reason="=reason",
        status=EligibilityStatus.ATTENDANCE_INSUFFICIENT,
    )

    _ = generate_ineligibility_report([entry], str(output_path))

    workbook_xml = _workbook_xml(output_path)

    assert "'=cmd|' /C calc'!A0" in workbook_xml
    assert "'+Zoom Name" in workbook_xml
    assert "'-matched" in workbook_xml
    assert "'@APA" in workbook_xml
    assert "'=reason" in workbook_xml
