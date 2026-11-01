"""A damaged .xlsx is a clear 400, never a 500 (synthetic data)."""

from __future__ import annotations

import asyncio
import zipfile
from typing import TYPE_CHECKING

import pytest
from fastapi import HTTPException
from src.backends.routes import ParseRequest, parse_endpoint
from src.parser.tabular import UnreadableFileError, read_rows

from tests.synthetic import at, seg, write_qualtrics, write_zoom

if TYPE_CHECKING:
    from pathlib import Path


def _truncate_sheet(good: Path, bad: Path) -> Path:
    """Copy a workbook, cutting each worksheet's XML in half."""
    with zipfile.ZipFile(good) as src, zipfile.ZipFile(bad, "w") as dst:
        for name in src.namelist():
            data = src.read(name)
            if name.startswith("xl/worksheets/sheet"):
                data = data[: len(data) // 2]
            dst.writestr(name, data)
    return bad


@pytest.fixture
def files(tmp_path: Path) -> tuple[Path, Path, Path]:
    zoom = write_zoom(
        tmp_path / "zoom.xlsx",
        [seg("Olive Ontime", "olive@example.test", at(9, 0), at(12, 0))],
    )
    qualtrics = write_qualtrics(
        tmp_path / "q.xlsx",
        [("Olive Ontime", "olive@example.test", "Psychologist (APA)", None)],
    )
    broken = _truncate_sheet(qualtrics, tmp_path / "broken.xlsx")
    return zoom, qualtrics, broken


def test_truncated_sheet_xml_is_unreadable(files: tuple[Path, Path, Path]) -> None:
    with pytest.raises(UnreadableFileError, match=r"broken\.xlsx"):
        read_rows(str(files[2]))


def test_parse_returns_400_for_a_truncated_qualtrics_file(
    files: tuple[Path, Path, Path],
) -> None:
    zoom, _, broken = files
    request = ParseRequest.model_validate({"zoom_path": str(zoom), "qualtrics_path": str(broken)})
    with pytest.raises(HTTPException) as caught:
        asyncio.run(parse_endpoint(request))
    assert caught.value.status_code == 400
    assert "broken.xlsx" in str(caught.value.detail)


def test_parse_returns_400_for_a_truncated_zoom_file(
    files: tuple[Path, Path, Path], tmp_path: Path
) -> None:
    zoom, qualtrics, _ = files
    broken_zoom = _truncate_sheet(zoom, tmp_path / "broken_zoom.xlsx")
    request = ParseRequest.model_validate(
        {"zoom_path": str(broken_zoom), "qualtrics_path": str(qualtrics)}
    )
    with pytest.raises(HTTPException) as caught:
        asyncio.run(parse_endpoint(request))
    assert caught.value.status_code == 400
