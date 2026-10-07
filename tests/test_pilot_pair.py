"""Synthetic Zoom + Qualtrics pair covering every shipped certificate type."""

from __future__ import annotations

import shutil
import subprocess
from datetime import date, time
from pathlib import Path

from src.generator.templates import format_training_date, resolve_template_key
from src.generator.zoom_host import extract_zoom_host
from src.models.certificate import EligibilityStatus
from src.pipeline import PipelineResult, run_pipeline

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_ZOOM = _FIXTURES / "pilot_zoom.xlsx"
_QUALTRICS = _FIXTURES / "pilot_qualtrics.xlsx"

_TITLE = "Ethics and Practice in School-Based Mental Health"
_INSTRUCTOR = "Dr. Amira Solano"
_LOCATION = "Rutgers University in Piscataway, NJ"


def _run(
    tmp_path: Path,
    *,
    is_virtual: bool = True,
    location: str | None = None,
    end_date: date | None = None,
) -> PipelineResult:
    return run_pipeline(
        zoom_path=str(_ZOOM),
        qualtrics_path=str(_QUALTRICS),
        title=_TITLE,
        training_date=date(2026, 10, 6),
        instructor=_INSTRUCTOR,
        ce_credits=3,
        ce_types=["APA", "NASP", "NY", "NBCC"],
        start_time=time(9, 0),
        end_time=time(12, 0),
        output_dir=str(tmp_path),
        excluded_names={"Morgan Hale"},
        is_virtual=is_virtual,
        location=location,
        end_date=end_date,
    )


def _pdf_text(path: Path) -> str:
    executable = shutil.which("pdftotext")
    if executable is None:
        msg = "pdftotext is required to read generated certificates"
        raise RuntimeError(msg)
    completed = subprocess.run(  # noqa: S603
        [executable, "-layout", str(path), "-"],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def test_zoom_host_is_the_synthetic_host() -> None:
    assert extract_zoom_host(str(_ZOOM)) == "Morgan Hale"


def test_pilot_pair_generates_every_ce_type(tmp_path: Path) -> None:
    result = _run(tmp_path)

    assert result.errors == []
    assert result.total_requests == 14
    assert len(result.eligible) == 8
    assert len(result.ineligible) == 6

    keys = [resolve_template_key(str(cert.ce_type)) for cert in result.eligible]
    assert sorted(keys) == [
        "apa",
        "apa",
        "apa",
        "attendance",
        "nasp",
        "nbcc",
        "ny",
        "ny",
    ]

    licenses = sorted(
        cert.license_number
        for cert in result.eligible
        if resolve_template_key(str(cert.ce_type)) == "ny"
    )
    assert licenses == ["012345", "067890"]

    by_status: dict[EligibilityStatus, int] = {}
    for entry in result.ineligible:
        by_status[entry.status] = by_status.get(entry.status, 0) + 1
    assert by_status == {
        EligibilityStatus.EXCLUDED: 1,
        EligibilityStatus.ATTENDANCE_INSUFFICIENT: 3,
        EligibilityStatus.NOT_FOUND_IN_ATTENDANCE: 1,
        EligibilityStatus.NAME_MATCH_AMBIGUOUS: 1,
    }
    assert all(entry.status != EligibilityStatus.CE_TYPE_NOT_OFFERED for entry in result.ineligible)

    pdfs = sorted(tmp_path.glob("*.pdf"))
    assert len(pdfs) == 8
    assert all(path.stat().st_size > 0 and path.read_bytes()[:5] == b"%PDF-" for path in pdfs)
    assert (tmp_path / "ineligibility_report.xlsx").is_file()

    texts = {path.name: _pdf_text(path) for path in pdfs}
    combined = "\n".join(texts.values())
    assert "Avery Chen" in combined
    assert "Samira N. Patel" in combined
    assert "Quinn Alvarez" in combined
    assert "012345" in combined
    assert "067890" in combined
    assert "Morgan Hale" not in combined
    assert "Taylor Brooks" not in combined
    assert "Rowan Blake" not in combined
    assert "Noah Blake" not in combined
    assert _TITLE in combined
    assert "October 6, 2026" in combined

    for path in tmp_path.iterdir():
        path.unlink()
    again = _run(tmp_path)
    assert again.errors == []
    assert len(list(tmp_path.glob("*.pdf"))) == 8
    assert (tmp_path / "ineligibility_report.xlsx").is_file()


def test_pilot_pair_in_person_multiday_wording(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        is_virtual=False,
        location=_LOCATION,
        end_date=date(2026, 10, 7),
    )
    date_range = format_training_date(date(2026, 10, 6), date(2026, 10, 7))
    assert result.errors == []
    assert len(list(tmp_path.glob("*.pdf"))) == 8

    by_key: dict[str, str] = {}
    for cert, path in zip(result.eligible, result.generated_paths, strict=True):
        key = resolve_template_key(str(cert.ce_type))
        by_key.setdefault(key, _pdf_text(Path(path)))

    assert set(by_key) == {"apa", "ny", "nasp", "nbcc", "attendance"}
    assert date_range in by_key["apa"]
    assert _LOCATION in by_key["apa"]
    assert "In-Person" in by_key["apa"]
    assert _LOCATION in by_key["ny"]
    assert f"at {_LOCATION}" in by_key["nasp"]
    assert "via Live Zoom Webinar" not in by_key["nasp"]
    assert "9:00 AM" in by_key["nasp"]
    assert "12:00 PM" in by_key["nasp"]
    assert _LOCATION in by_key["nbcc"]
    assert _LOCATION in by_key["attendance"]
    assert date_range in by_key["attendance"]
