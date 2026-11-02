"""Demo: verify all 5 certificate types can be generated end-to-end."""
from datetime import date, datetime, time
from pathlib import Path

from src.pipeline import run_pipeline
from tests.synthetic import write_zoom, write_qualtrics


def _dt(year: int, month: int, day: int, hour: int, minute: int) -> datetime:
    return datetime(year, month, day, hour, minute)


def test_all_five_certificate_types_generate(tmp_path: Path) -> None:
    """APA, NASP, NY, NBCC, and Attendance certificates all generate."""
    zoom_rows = [
        ("Alice Anderson", "alice@example.test", _dt(2026,11,2,8,45), _dt(2026,11,2,12,15), "No"),
        ("Bob Martinez", "bob@example.test", _dt(2026,11,2,8,50), _dt(2026,11,2,12,10), "No"),
        ("Carol Chen", "carol@example.test", _dt(2026,11,2,8,48), _dt(2026,11,2,12,12), "No"),
        ("David Kim", "david@example.test", _dt(2026,11,2,8,55), _dt(2026,11,2,12,8), "No"),
        ("Elena Volkov", "elena@example.test", _dt(2026,11,2,8,52), _dt(2026,11,2,12,14), "No"),
    ]
    zoom_path = tmp_path / "zoom.xlsx"
    write_zoom(zoom_path, zoom_rows, meeting_start=_dt(2026,11,2,8,47), meeting_end=_dt(2026,11,2,12,11))

    qualtrics_rows = [
        ("Alice Anderson", "alice@example.test", "Psychologist (APA)", None),
        ("Bob Martinez", "bob@example.test", "School Psychologist (NASP)", None),
        ("Carol Chen", "carol@example.test", "Psychologist (New York)", "NY-12345"),
        ("David Kim", "david@example.test", "Certified Neighbor (NBCC)", None),
        ("Elena Volkov", "elena@example.test", "Attendance Certificate", None),
    ]
    qualtrics_path = tmp_path / "qualtrics.xlsx"
    write_qualtrics(qualtrics_path, qualtrics_rows)

    result = run_pipeline(
        zoom_path=str(zoom_path),
        qualtrics_path=str(qualtrics_path),
        title="Demo Training",
        training_date=date(2026, 11, 2),
        instructor="Dr. Demo",
        ce_credits=3.5,
        ce_types=["APA", "NASP", "NY", "NBCC", "Attendance"],
        start_time=time(8, 47),
        end_time=time(12, 11),
        output_dir=str(tmp_path),
    )

    assert result.errors == []
    assert result.ineligible == []
    assert len(result.eligible) == 5

    ce_types = {str(c.ce_type) for c in result.eligible}
    assert ce_types == {"Psychologist (APA)", "School Psychologist (NASP)", "Psychologist (New York)", "Certified Neighbor (NBCC)", "Attendance Certificate"}

    pdfs = sorted(tmp_path.glob("*.pdf"))
    assert len(pdfs) == 5
    for pdf in pdfs:
        assert pdf.stat().st_size > 1000, f"{pdf.name} too small"
