"""Smaller review findings, each with synthetic inputs."""

from __future__ import annotations

import asyncio
import json
import zlib
from datetime import date, time
from pathlib import Path

import pytest
from src import pipeline
from src.backends import routes
from src.backends.routes import PreviewRequest, preview_endpoint
from src.generator import certificate as certificate_module
from src.generator.certificate import pdf_page_count
from src.models.certificate import CertificateOutput
from src.models.participant import normalize_name
from src.models.training import CEType
from src.pipeline import run_pipeline

from tests.synthetic import at, seg, write_qualtrics, write_zoom


# ── Page count inside compressed object streams ──────────────────────────────


def _objstm_pdf(path: Path, pages: int) -> Path:
    """A PDF 1.5 file whose page objects live only in a compressed ObjStm."""
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>"]
    kids = " ".join(f"{i + 3} 0 R" for i in range(pages))
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {pages} >>".encode())
    objects += [b"<< /Type /Page /Parent 2 0 R >>"] * pages
    body = b" ".join(objects)
    offsets, pos = [], 0
    for obj in objects:
        offsets.append(pos)
        pos += len(obj) + 1
    header = " ".join(f"{i + 1} {off}" for i, off in enumerate(offsets)).encode() + b" "
    packed = zlib.compress(header + body)
    path.write_bytes(
        b"%PDF-1.5\n10 0 obj\n"
        + f"<< /Type /ObjStm /N {len(objects)} /First {len(header)} ".encode()
        + f"/Filter /FlateDecode /Length {len(packed)} >>\nstream\n".encode()
        + packed
        + b"\nendstream\nendobj\n%%EOF\n"
    )
    return path


@pytest.mark.parametrize("pages", [1, 2])
def test_page_count_reads_object_streams(tmp_path: Path, pages: int) -> None:
    assert pdf_page_count(_objstm_pdf(tmp_path / f"{pages}.pdf", pages)) == pages


# ── Filenames and all-caps names ─────────────────────────────────────────────


def _output(name: str) -> CertificateOutput:
    return CertificateOutput(
        full_name=name,
        ce_type=CEType("Psychologist (APA)"),
        ce_credits=3,
        training_title="Ethics",
        training_date=date(2026, 11, 2),
        instructor_name="Dr. Pat Presenter, Ph.D.",
        license_number=None,
        issue_date=date(2026, 11, 2),
    )


@pytest.mark.parametrize(
    ("name", "stem"),
    [
        ("Mark Roe, Ph.D.", "Roe_CECertificate_Presenter_11.2.26"),
        ("Mark Roe PhD", "Roe_CECertificate_Presenter_11.2.26"),
        ("Mark Roe, M.A., LPC", "Roe_CECertificate_Presenter_11.2.26"),
        ("Li Ma", "Ma_CECertificate_Presenter_11.2.26"),
    ],
)
def test_filename_uses_the_surname_not_a_credential(name: str, stem: str) -> None:
    assert _output(name).output_basename == stem


def test_all_caps_name_keeps_a_surname_that_looks_like_a_credential() -> None:
    assert normalize_name("KIM LI MA") == "kim li ma"
    # A real credential after a comma is still dropped.
    assert normalize_name("KIM LI, MA") == "kim li"
    # Mixed case keeps the old rule: capital MA is a degree.
    assert normalize_name("Kim Li MA") == "kim li"


# ── Preview warnings ─────────────────────────────────────────────────────────


def test_preview_reports_unsupported_characters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_generate(output: CertificateOutput, out_dir: str, **_kw: object) -> str:
        path = Path(out_dir) / "preview.pdf"
        path.write_bytes(
            b"%PDF-1.7\n1 0 obj << /Type /Page >> endobj\n%%EOF\n"
        )
        return str(path)

    monkeypatch.setattr(routes, "generate_certificate", fake_generate)
    request = PreviewRequest.model_validate(
        {
            "full_name": "\u738b\u5c0f\u660e",
            "ce_type": "Psychologist (APA)",
            "ce_credits": 3,
            "training_title": "Ethics",
            "training_date": "2026-11-02",
            "instructor_name": "Pat Presenter",
        }
    )
    response = asyncio.run(preview_endpoint(request))
    raw = response.headers.get("x-certificate-warnings")
    assert raw is not None
    warnings = json.loads(raw)
    assert len(warnings) == 1
    assert "\u738b" in warnings[0]


# ── Reruns into the same folder say which file is current ────────────────────


def test_rerun_warns_which_files_are_current(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_generate(
        output: CertificateOutput, out_dir: str, *, basename: str | None = None, **_kw: object
    ) -> str:
        path = Path(out_dir) / f"{basename or output.output_basename}.pdf"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"%PDF-1.7\n1 0 obj << /Type /Page >> endobj\n%%EOF\n")
        return str(path)

    monkeypatch.setattr(certificate_module, "generate_certificate", fake_generate)
    zoom = write_zoom(
        tmp_path / "zoom.xlsx",
        [
            seg("Olive Ontime", "olive@example.test", at(9, 0), at(12, 0)),
            seg("Lou Late", "lou@example.test", at(9, 40), at(12, 0)),
        ],
    )
    qualtrics = write_qualtrics(
        tmp_path / "q.xlsx",
        [
            ("Olive Ontime", "olive@example.test", "Psychologist (APA)", None),
            ("Lou Late", "lou@example.test", "Psychologist (APA)", None),
        ],
    )
    out = tmp_path / "out"

    def run() -> pipeline.PipelineResult:
        return run_pipeline(
            str(zoom), str(qualtrics), "T", date(2026, 11, 2), "Pat Presenter", 3, ["APA"],
            time(9, 0), time(12, 0), output_dir=str(out),
        )

    first = run()
    assert not [w for w in first.warnings if "current" in w]
    second = run()
    assert Path(second.generated_paths[0]).name == "Ontime_CECertificate_Presenter_11.2.26_2.pdf"
    current = [w for w in second.warnings if "current" in w]
    assert any(
        "Ontime_CECertificate_Presenter_11.2.26_2.pdf" in w
        and "Ontime_CECertificate_Presenter_11.2.26.pdf" in w
        for w in current
    ), second.warnings
    assert any("ineligibility_report_2.xlsx" in w for w in current), second.warnings
