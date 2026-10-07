"""CLI entry point against the synthetic Zoom + Qualtrics pair."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_cli_generates_pilot_certificates(tmp_path: Path) -> None:
    completed = subprocess.run(  # noqa: S603
        [
            sys.executable,
            str(_ROOT / "certgen.py"),
            "--title",
            "Ethics and Practice in School-Based Mental Health",
            "--date",
            "2026-10-06",
            "--instructor",
            "Dr. Amira Solano",
            "--ce-credits",
            "3",
            "--ce-types",
            "APA,NASP,NY,NBCC",
            "--start-time",
            "09:00",
            "--end-time",
            "12:00",
            "--exclude",
            "Morgan Hale",
            "--zoom-report",
            str(_FIXTURES / "pilot_zoom.xlsx"),
            "--qualtrics-report",
            str(_FIXTURES / "pilot_qualtrics.xlsx"),
            "--output-dir",
            str(tmp_path),
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=_ROOT,
    )
    assert completed.returncode == 0, completed.stderr
    assert "Total CE requests: 14" in completed.stdout
    assert "Eligible: 8" in completed.stdout
    assert "Ineligible: 6" in completed.stdout
    assert "Certificates generated: 8" in completed.stdout
    assert len(list(tmp_path.glob("*.pdf"))) == 8
    assert (tmp_path / "ineligibility_report.xlsx").is_file()


def test_cli_requires_location_for_in_person() -> None:
    completed = subprocess.run(  # noqa: S603
        [
            sys.executable,
            str(_ROOT / "certgen.py"),
            "--title",
            "Ethics",
            "--date",
            "2026-10-06",
            "--instructor",
            "Dr. Amira Solano",
            "--ce-credits",
            "3",
            "--ce-types",
            "APA",
            "--start-time",
            "09:00",
            "--end-time",
            "12:00",
            "--in-person",
            "--zoom-report",
            str(_FIXTURES / "pilot_zoom.xlsx"),
            "--qualtrics-report",
            str(_FIXTURES / "pilot_qualtrics.xlsx"),
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=_ROOT,
    )
    assert completed.returncode == 1
    assert "location" in completed.stderr.lower()
