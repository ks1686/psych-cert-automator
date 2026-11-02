"""The CLI leaves the Zoom host out, like the desktop app does."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import src.pipeline as pipeline
from click.testing import CliRunner

import certgen
from tests.synthetic import at, seg, write_qualtrics, write_zoom

if TYPE_CHECKING:
    from pathlib import Path

APA = "Psychologist (APA)"


def _run(tmp_path: Path, *extra: str) -> tuple[str, list[str]]:
    zoom = write_zoom(
        tmp_path / "z.xlsx",
        [
            seg("Hana Host", "hana.host@example.test", at(8, 50), at(12, 5)),
            seg("Ada Lovelace", "ada@example.test", at(9, 0), at(12, 0)),
        ],
    )
    qualtrics = write_qualtrics(
        tmp_path / "q.xlsx",
        [
            ("Hana Host", "hana.host@example.test", APA, None),
            ("Ada Lovelace", "ada@example.test", APA, None),
        ],
    )
    generated: list[str] = []

    def fake_generate(outputs: list, _d: str, **_k: object) -> list[str]:
        generated.extend(o.full_name for o in outputs)
        return [f"{i}.pdf" for i in range(len(outputs))]

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(pipeline, "generate_all", fake_generate)
        result = CliRunner().invoke(
            certgen.main,
            [
                "--title", "Ethics", "--date", "2026-11-02", "--instructor", "Dr. G",
                "--ce-credits", "3", "--ce-types", "APA",
                "--start-time", "09:00", "--end-time", "12:00",
                "--zoom-report", str(zoom), "--qualtrics-report", str(qualtrics),
                "--output-dir", str(tmp_path / "out"), *extra,
            ],
        )
    assert result.exit_code == 0, result.output
    return result.output, generated


def test_cli_excludes_the_zoom_host_by_default(tmp_path: Path) -> None:
    output, generated = _run(tmp_path)
    assert generated == ["Ada Lovelace"]
    assert "Hana Host" in output


def test_cli_can_include_the_host(tmp_path: Path) -> None:
    _output, generated = _run(tmp_path, "--include-host")
    assert sorted(generated) == ["Ada Lovelace", "Hana Host"]
