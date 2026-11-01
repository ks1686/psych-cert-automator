"""Certificates that may not render correctly must be reported, not hidden."""

from __future__ import annotations

from datetime import date, time
from typing import TYPE_CHECKING

import src.pipeline as pipeline
from src.generator.certificate import certificate_warnings, pdf_page_count
from src.models.certificate import CertificateOutput
from src.models.training import CEType
from src.pipeline import run_pipeline

from tests.synthetic import at, seg, write_qualtrics, write_zoom

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def _pdf(path: Path, pages: int) -> Path:
    body = b"".join(
        f"{i + 3} 0 obj << /Type /Page /Parent 2 0 R >> endobj\n".encode() for i in range(pages)
    )
    path.write_bytes(
        b"%PDF-1.7\n1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
        + f"2 0 obj << /Type /Pages /Count {pages} >> endobj\n".encode()
        + body
        + b"%%EOF\n"
    )
    return path


def _output(name: str, title: str = "Ethics") -> CertificateOutput:
    return CertificateOutput(
        full_name=name,
        ce_type=CEType("Psychologist (APA)"),
        ce_credits=3,
        training_title=title,
        training_date=date(2026, 11, 2),
        instructor_name="Dr. Grace Hopper",
        license_number=None,
    )


def test_page_count(tmp_path: Path) -> None:
    assert pdf_page_count(_pdf(tmp_path / "one.pdf", 1)) == 1
    assert pdf_page_count(_pdf(tmp_path / "two.pdf", 2)) == 2


def test_two_page_certificate_is_flagged(tmp_path: Path) -> None:
    warnings = certificate_warnings(_output("Ada Lovelace"), str(_pdf(tmp_path / "c.pdf", 2)))
    assert any("2 pages" in w for w in warnings)
    assert certificate_warnings(_output("Ada Lovelace"), str(_pdf(tmp_path / "d.pdf", 1))) == []


def test_unsupported_script_is_flagged(tmp_path: Path) -> None:
    pdf = str(_pdf(tmp_path / "c.pdf", 1))
    [warning] = certificate_warnings(_output("王小明"), pdf)
    assert "王小明" in warning
    assert certificate_warnings(_output("José Núñez-O’Neil"), pdf) == []
    assert certificate_warnings(_output("Ada", title="Ethics – 第二部"), pdf)


def test_pipeline_surfaces_render_warnings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    zoom = write_zoom(tmp_path / "z.xlsx", [seg("王小明", "wang@example.test", at(9, 0), at(12, 0))])
    qualtrics = write_qualtrics(
        tmp_path / "q.xlsx", [("王小明", "wang@example.test", "Psychologist (APA)", None)],
    )
    monkeypatch.setattr(
        pipeline, "generate_all", lambda outputs, _d, **_k: [f"{i}.pdf" for i in range(len(outputs))]
    )
    result = run_pipeline(
        str(zoom), str(qualtrics), "T", date(2026, 11, 2), "P", 3, ["APA"],
        time(9, 0), time(12, 0), output_dir=str(tmp_path / "out"),
    )
    assert len(result.eligible) == 1
    assert any("王小明" in w for w in result.warnings)
