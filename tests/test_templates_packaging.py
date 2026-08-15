"""Packaging: frozen template resolution and PyInstaller spec contents."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest  # noqa: TC002
from src.generator import templates as templates_mod

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SPEC = _REPO_ROOT / "build" / "psych-cert-gen.spec"


def test_templates_dir_uses_repo_templates_when_not_frozen() -> None:
    if hasattr(sys, "_MEIPASS"):
        delattr(sys, "_MEIPASS")
    path = templates_mod.templates_dir()
    assert path == _REPO_ROOT / "templates"
    assert (path / "apa.docx").is_file()


def test_templates_dir_uses_meipass_when_frozen(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundled = tmp_path / "templates"
    bundled.mkdir()
    _ = (bundled / "apa.docx").write_bytes(b"PK")
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert templates_mod.templates_dir() == bundled
    assert templates_mod.template_path_for("APA") == bundled / "apa.docx"


def test_pyinstaller_spec_bundles_templates_and_lxml() -> None:
    text = _SPEC.read_text(encoding="utf-8")
    assert "datas=" in text
    assert "templates" in text
    assert "apa.docx" in text
    assert "lxml" in text
    assert '"fpdf"' not in text
    assert "'fpdf'" not in text
    assert "httpx" not in text
    assert '"yaml"' not in text
    assert "'yaml'" not in text
