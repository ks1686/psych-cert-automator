"""Pipeline: offered CE types filter Qualtrics generation."""

from __future__ import annotations

from datetime import date, time
from pathlib import Path

from src.models.certificate import EligibilityStatus
from src.pipeline import run_pipeline

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_ce_types_filter_rejects_unoffered_apa(tmp_path: Path) -> None:
    result = run_pipeline(
        zoom_path=str(_FIXTURES / "sample_zoom.xlsx"),
        qualtrics_path=str(_FIXTURES / "sample_qualtrics.xlsx"),
        title="Ethics Training",
        training_date=date(2026, 3, 20),
        instructor="Dr. Jane Smith",
        ce_credits=3,
        ce_types=["NASP"],
        start_time=time(8, 47),
        end_time=time(12, 11),
        output_dir=str(tmp_path),
    )
    assert result.errors == []
    rejected = [
        entry
        for entry in result.ineligible
        if entry.status == EligibilityStatus.CE_TYPE_NOT_OFFERED
    ]
    assert rejected
    assert all("not offered" in entry.reason.lower() for entry in rejected)
    assert all(
        str(cert.ce_type).upper().find("APA") == -1 for cert in result.eligible
    )


def test_unknown_qualtrics_type_still_gets_attendance(tmp_path: Path) -> None:
    result = run_pipeline(
        zoom_path=str(_FIXTURES / "sample_zoom.xlsx"),
        qualtrics_path=str(_FIXTURES / "sample_qualtrics.xlsx"),
        title="Ethics Training",
        training_date=date(2026, 3, 20),
        instructor="Dr. Jane Smith",
        ce_credits=3,
        ce_types=["APA", "NASP", "NY", "NBCC"],
        start_time=time(8, 47),
        end_time=time(12, 11),
        output_dir=str(tmp_path),
    )
    assert result.errors == []
    not_offered = [
        entry
        for entry in result.ineligible
        if entry.status == EligibilityStatus.CE_TYPE_NOT_OFFERED
    ]
    assert not_offered == []
