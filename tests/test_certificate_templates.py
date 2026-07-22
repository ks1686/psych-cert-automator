"""Tests for Word-template certificate mapping and filename conventions."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from zipfile import ZipFile

from src.generator.certificate import CertificateRenderOptions, generate_certificate
from src.generator.templates import (
    format_training_date,
    resolve_template_key,
    template_path_for,
)
from src.models.certificate import CertificateOutput
from src.models.training import CEType


def test_resolve_template_key_maps_known_types() -> None:
    assert resolve_template_key("Psychologist (APA)") == "apa"
    assert resolve_template_key("APA") == "apa"
    assert resolve_template_key("Psychologist (New York)") == "ny"
    assert resolve_template_key("NY") == "ny"
    assert resolve_template_key("NASP") == "nasp"
    assert resolve_template_key("BCBA") == "attendance"
    assert resolve_template_key("Something Else") == "attendance"


def test_template_files_exist() -> None:
    for ce in ("APA", "NY", "NASP", "Other"):
        path = template_path_for(ce)
        assert path.is_file()
        assert path.suffix == ".docx"


def test_output_filename_pattern() -> None:
    out = CertificateOutput(
        full_name="Jessica Benas",
        ce_type=CEType("APA"),
        ce_credits=3,
        training_title="Ethics",
        training_date=date(2026, 3, 20),
        instructor_name="Dr. Jane Smith",
        license_number=None,
        issue_date=date(2026, 3, 21),
    )
    assert out.output_basename == "Benas_CECertificate_Smith_2026-03-20"
    assert out.output_filename == "Benas_CECertificate_Smith_2026-03-20.pdf"


def test_output_filename_sanitizes_at_sign() -> None:
    out = CertificateOutput(
        full_name="Pat O@Brien",
        ce_type=CEType("APA"),
        ce_credits=1,
        training_title="T",
        training_date=date(2026, 1, 2),
        instructor_name="Alex",
        license_number=None,
        issue_date=date(2026, 1, 2),
    )
    assert "@" not in out.output_filename
    assert out.output_basename.startswith("O_Brien_CECertificate_")


def test_format_training_date_range() -> None:
    assert format_training_date(date(2026, 3, 18), date(2026, 3, 20)) == (
        "March 18–20, 2026"
    )
    assert format_training_date(date(2026, 3, 20)) == "March 20, 2026"


def test_generate_certificate_writes_filled_docx(tmp_path: Path) -> None:
    out = CertificateOutput(
        full_name="Jamie Example",
        ce_type=CEType("Psychologist (APA)"),
        ce_credits=3,
        training_title="Sample Training",
        training_date=date(2026, 3, 20),
        instructor_name="Dr. Pat Instructor",
        license_number=None,
        issue_date=date(2026, 3, 21),
    )
    path = Path(
        generate_certificate(
            out,
            str(tmp_path),
            options=CertificateRenderOptions(is_virtual=True),
        )
    )
    assert path.exists()
    # Soft-fail may leave .docx when PDF tools are missing.
    assert path.suffix.lower() in {".pdf", ".docx"}
    docx = path if path.suffix.lower() == ".docx" else path.with_suffix(".docx")
    assert docx.is_file()
    with ZipFile(docx) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")
    assert "Jamie Example" in xml
    assert "Sample Training" in xml
    assert ">NAME<" not in xml
