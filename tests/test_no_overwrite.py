"""A second run into the same folder must not overwrite earlier certificates."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import src.generator.certificate as certgen_module
from src.generator.certificate import generate_all
from src.generator.report import next_free_path
from src.models.certificate import CertificateOutput
from src.models.training import CEType

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def _output(name: str) -> CertificateOutput:
    return CertificateOutput(
        full_name=name,
        ce_type=CEType("Psychologist (APA)"),
        ce_credits=3,
        training_title="Ethics",
        training_date=date(2026, 11, 2),
        instructor_name="Dr. Grace Hopper",
        license_number=None,
        issue_date=date(2026, 11, 2),
    )


def test_existing_certificate_files_are_not_reused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = _output("Ada Lovelace")
    earlier = tmp_path / f"{out.output_basename}.pdf"
    earlier.write_bytes(b"earlier run")
    used: list[str] = []

    def fake_generate(_req: object, output_dir: str, **kwargs: object) -> str:
        stem = str(kwargs["basename"])
        used.append(stem)
        return f"{output_dir}/{stem}.pdf"

    monkeypatch.setattr(certgen_module, "generate_certificate", fake_generate)
    generate_all([out], str(tmp_path))

    assert used == [f"{out.output_basename}_2"]
    assert earlier.read_bytes() == b"earlier run"


def test_word_fallback_files_also_count_as_taken(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = _output("Ada Lovelace")
    (tmp_path / f"{out.output_basename}.docx").write_bytes(b"earlier run")
    (tmp_path / f"{out.output_basename}_2.pdf").write_bytes(b"earlier run")
    used: list[str] = []
    monkeypatch.setattr(
        certgen_module,
        "generate_certificate",
        lambda _r, d, **k: used.append(str(k["basename"])) or f"{d}/x.pdf",
    )
    generate_all([out], str(tmp_path))
    assert used == [f"{out.output_basename}_3"]


def test_report_path_does_not_overwrite(tmp_path: Path) -> None:
    first = tmp_path / "ineligibility_report.xlsx"
    assert next_free_path(first) == first
    first.write_bytes(b"x")
    assert next_free_path(first) == tmp_path / "ineligibility_report_2.xlsx"
