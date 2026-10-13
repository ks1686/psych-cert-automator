"""Pixel and layout checks for every shipped certificate template.

Golden PNGs are rendered with pdftoppm at a fixed DPI from dxpdf output.
Regenerate them with UPDATE_CERTIFICATE_GOLDENS=1 after an intentional
layout change.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import date, time
from pathlib import Path

import pytest
from PIL import Image, ImageChops
from src.generator.certificate import CertificateRenderOptions, generate_certificate
from src.generator.templates import resolve_template_key
from src.models.certificate import CertificateOutput, EligibilityStatus
from src.models.training import CEType
from src.pipeline import run_pipeline

_ROOT = Path(__file__).resolve().parents[1]
_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_GOLDEN = _FIXTURES / "golden"
_DPI = 96
_PIXEL_DIFF_LIMIT = 0.001
_PAGE_INSET = 8.0
_TITLE = "Ethics and Practice in School-Based Mental Health"
_INSTRUCTOR = "Dr. Amira Solano"
_WHEN = date(2026, 10, 6)
_START = time(9, 0)
_END = time(12, 0)
_LONG_TITLE = (
    "Supporting Multilingual Learners Across Multi-Tiered Systems of Support "
    "in Urban School Districts"
)
_LONG_LOCATION = "Hôpital Saint-Louis Annex, 1000 Long Street Name, City"
_PLACEHOLDER_RE = re.compile(
    r"\bNAME\b|\bTITLE\b|Program title|Name, Degree|TIME\s*[\u2013\u2014-]\s*TIME|"
    r"X continuing|HYPERLINK|nj-charactered|Gordon Road"
)
_WORD_RE = re.compile(
    r'<word xMin="([^"]+)" yMin="([^"]+)" xMax="([^"]+)" yMax="([^"]+)">([^<]*)</word>'
)
_PAGE_RE = re.compile(r'<page width="([^"]+)" height="([^"]+)"')

_LANDSCAPE = frozenset({"apa", "ny", "nbcc"})
_PORTRAIT = frozenset({"nasp", "attendance"})


@dataclass(frozen=True, slots=True)
class _RenderCase:
    stem: str
    ce_type: str
    full_name: str
    title: str
    license_number: str | None
    location: str | None
    end_date: date | None
    is_virtual: bool
    golden: bool


def _case(  # noqa: PLR0913
    stem: str,
    ce_type: str,
    full_name: str,
    title: str,
    license_number: str | None,
    location: str | None,
    end_date: date | None,
    *,
    is_virtual: bool,
    golden: bool,
) -> _RenderCase:
    return _RenderCase(
        stem,
        ce_type,
        full_name,
        title,
        license_number,
        location,
        end_date,
        is_virtual=is_virtual,
        golden=golden,
    )


_CASES: tuple[_RenderCase, ...] = (
    _case("apa", "APA", "Avery Chen", _TITLE, None, None, None, is_virtual=True, golden=True),
    _case(
        "ny",
        "Psychologist (New York)",
        "Riley Okonkwo",
        _TITLE,
        "012345",
        None,
        None,
        is_virtual=True,
        golden=True,
    ),
    _case(
        "nasp",
        "NASP",
        "Samira N. Patel",
        _TITLE,
        None,
        None,
        None,
        is_virtual=True,
        golden=True,
    ),
    _case(
        "nbcc",
        "Counselor (NBCC)",
        "Jordan Ellis",
        _TITLE,
        None,
        None,
        None,
        is_virtual=True,
        golden=True,
    ),
    _case(
        "attendance",
        "Certificate of Attendance",
        "Quinn Alvarez",
        _TITLE,
        None,
        None,
        None,
        is_virtual=True,
        golden=True,
    ),
    _case(
        "attendance-long",
        "Certificate of Attendance",
        "Alexandria Montgomery-O'Brien",
        _LONG_TITLE,
        None,
        _LONG_LOCATION,
        None,
        is_virtual=False,
        golden=True,
    ),
    _case(
        "ny-no-license",
        "NY",
        "Renée Chloé D'Amico",
        "Short Title",
        None,
        None,
        None,
        is_virtual=True,
        golden=True,
    ),
    _case(
        "apa-stress",
        "APA",
        "José Núñez-García",
        _LONG_TITLE,
        None,
        _LONG_LOCATION,
        date(2026, 10, 8),
        is_virtual=False,
        golden=False,
    ),
    _case(
        "ny-stress",
        "NY",
        "Mary-Jane O'Connor",
        _LONG_TITLE,
        "NY-123456",
        _LONG_LOCATION,
        date(2026, 10, 8),
        is_virtual=False,
        golden=False,
    ),
    _case(
        "nasp-stress",
        "NASP",
        "Siobhán Máire O'Sullivan-Pérez",
        _LONG_TITLE,
        None,
        None,
        date(2026, 10, 8),
        is_virtual=True,
        golden=False,
    ),
    _case(
        "nbcc-stress",
        "NBCC",
        "Jean-Luc François Saint-Étienne",
        _LONG_TITLE,
        None,
        None,
        None,
        is_virtual=True,
        golden=False,
    ),
    _case(
        "attendance-stress",
        "Other",
        "Zoë Ångström",
        _LONG_TITLE,
        None,
        _LONG_LOCATION,
        date(2026, 10, 8),
        is_virtual=False,
        golden=False,
    ),
)


def _require_tool(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        pytest.skip(f"{name} is required for certificate layout checks")
    return path


def _render(case: _RenderCase, output_dir: Path) -> Path:
    certificate = CertificateOutput(
        full_name=case.full_name,
        ce_type=CEType(case.ce_type),
        ce_credits=3,
        training_title=case.title,
        training_date=_WHEN,
        instructor_name=_INSTRUCTOR,
        license_number=case.license_number,
        issue_date=date(2026, 10, 7),
    )
    path = Path(
        generate_certificate(
            certificate,
            str(output_dir),
            options=CertificateRenderOptions(
                is_virtual=case.is_virtual,
                location=case.location,
                end_date=case.end_date,
                session_start=_START,
                session_end=_END,
            ),
            basename=case.stem,
        )
    )
    assert path.suffix.lower() == ".pdf", path
    return path


def _pdf_text(pdf: Path) -> str:
    completed = subprocess.run(  # noqa: S603
        [_require_tool("pdftotext"), "-layout", "-enc", "UTF-8", str(pdf), "-"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout


def _page_boxes(
    pdf: Path,
) -> list[tuple[float, float, list[tuple[float, float, float, float, str]]]]:
    raw = subprocess.run(  # noqa: S603
        [_require_tool("pdftotext"), "-bbox-layout", str(pdf), "-"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    pages: list[tuple[float, float, list[tuple[float, float, float, float, str]]]] = []
    for chunk in raw.split("<page ")[1:]:
        size = _PAGE_RE.search("<page " + chunk)
        assert size is not None
        words = [
            (float(x0), float(y0), float(x1), float(y1), text)
            for x0, y0, x1, y1, text in _WORD_RE.findall(chunk)
        ]
        pages.append((float(size.group(1)), float(size.group(2)), words))
    return pages


def _render_png(pdf: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(  # noqa: S603
        [
            _require_tool("pdftoppm"),
            "-png",
            "-r",
            str(_DPI),
            "-singlefile",
            str(pdf),
            str(destination.with_suffix("")),
        ],
        check=True,
        capture_output=True,
    )
    assert destination.is_file()


def _pixel_diff_ratio(actual: Path, golden: Path) -> float:
    with Image.open(actual) as actual_image, Image.open(golden) as golden_image:
        left = actual_image.convert("RGB")
        right = golden_image.convert("RGB")
        if left.size != right.size:
            msg = f"size {left.size} != golden {right.size}"
            raise AssertionError(msg)
        diff = ImageChops.difference(left, right)
        raw = diff.tobytes()
        changed = sum(
            1
            for index in range(0, len(raw), 3)
            if raw[index] or raw[index + 1] or raw[index + 2]
        )
        return changed / (left.size[0] * left.size[1])


def _assert_layout(case: _RenderCase, pdf: Path) -> None:
    key = resolve_template_key(case.ce_type)
    info = subprocess.run(  # noqa: S603
        [_require_tool("pdfinfo"), str(pdf)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    assert re.search(r"^Pages:\s+1$", info, re.MULTILINE), info
    text = _pdf_text(pdf)
    normalized = " ".join(text.split())
    assert case.full_name in normalized
    assert case.title in normalized
    assert _PLACEHOLDER_RE.search(text) is None, text
    if case.license_number:
        assert case.license_number in text
    if key == "ny" and not case.license_number:
        assert "NY Psychology License" not in text
    if key == "nasp":
        assert "via Live Zoom Webinar" in text or "at " in text
        assert "Phone: (732) 445-2000" in text.replace("\n", " ") or _same_line(
            pdf, "Phone:", "445-2000"
        )
    if key == "attendance":
        _assert_attendance_name_slot(pdf, case.full_name)

    pages = _page_boxes(pdf)
    assert len(pages) == 1
    width, height, words = pages[0]
    if key in _LANDSCAPE:
        assert abs(width - 792) < 1
        assert abs(height - 612) < 1
    else:
        assert key in _PORTRAIT
        assert abs(width - 612) < 1
        assert abs(height - 792) < 1
    for x0, y0, x1, y1, word in words:
        assert x0 >= _PAGE_INSET, word
        assert y0 >= _PAGE_INSET, word
        assert x1 <= width - _PAGE_INSET, word
        assert y1 <= height - _PAGE_INSET, word
    _assert_no_overlap(words)
    _assert_fonts_embedded(pdf)


def _same_line(pdf: Path, left: str, right: str) -> bool:
    _width, _height, words = _page_boxes(pdf)[0]
    left_y = [y0 for _x0, y0, _x1, _y1, word in words if word == left]
    right_y = [y0 for _x0, y0, _x1, _y1, word in words if word == right]
    return any(abs(a - b) < 1 for a in left_y for b in right_y)


def _assert_attendance_name_slot(pdf: Path, full_name: str) -> None:
    _width, _height, words = _page_boxes(pdf)[0]
    certify = min(y0 for _x0, y0, _x1, _y1, word in words if word == "certify")
    attended = min(y0 for _x0, y0, _x1, _y1, word in words if word == "attended,")
    first = full_name.split(maxsplit=1)[0]
    name_y = [y0 for _x0, y0, _x1, _y1, word in words if word == first]
    assert name_y, full_name
    assert certify < min(name_y) < attended


def _assert_no_overlap(words: list[tuple[float, float, float, float, str]]) -> None:
    for index, left in enumerate(words):
        for right in words[index + 1 :]:
            x0 = max(left[0], right[0])
            y0 = max(left[1], right[1])
            x1 = min(left[2], right[2])
            y1 = min(left[3], right[3])
            if x1 - x0 > 2 and y1 - y0 > 4:
                msg = f"{left[4]!r} overlaps {right[4]!r}"
                raise AssertionError(msg)


def _assert_fonts_embedded(pdf: Path) -> None:
    listing = subprocess.run(  # noqa: S603
        [_require_tool("pdffonts"), str(pdf)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    rows = [line for line in listing.splitlines()[2:] if line.strip()]
    assert rows
    for line in rows:
        assert re.search(r"\byes\b", line), line


@pytest.mark.parametrize("case", _CASES, ids=[case.stem for case in _CASES])
def test_certificate_layout_and_golden(case: _RenderCase, tmp_path: Path) -> None:
    pdf = _render(case, tmp_path)
    _assert_layout(case, pdf)
    if not case.golden:
        return
    png = tmp_path / f"{case.stem}.png"
    _render_png(pdf, png)
    golden = _GOLDEN / f"{case.stem}.png"
    if os.environ.get("UPDATE_CERTIFICATE_GOLDENS") == "1":
        golden.parent.mkdir(parents=True, exist_ok=True)
        golden.write_bytes(png.read_bytes())
        return
    assert golden.is_file(), f"missing golden {golden.name}"
    ratio = _pixel_diff_ratio(png, golden)
    assert ratio <= _PIXEL_DIFF_LIMIT, f"{case.stem} pixel diff {ratio:.4%}"


def test_v1_mock_workbook_covers_every_certificate_type(tmp_path: Path) -> None:
    result = run_pipeline(
        zoom_path=str(_FIXTURES / "v1_zoom.xlsx"),
        qualtrics_path=str(_FIXTURES / "v1_qualtrics.xlsx"),
        title="Mock Ethics Institute",
        training_date=date(2026, 4, 16),
        instructor=_INSTRUCTOR,
        ce_credits=3,
        ce_types=["APA", "NASP", "NY", "NBCC"],
        start_time=_START,
        end_time=_END,
        output_dir=str(tmp_path),
        excluded_names={"Morgan Hale"},
    )
    assert result.errors == []
    assert result.total_requests == 33
    assert len(result.eligible) == 27
    assert len(result.ineligible) == 6
    keys = {resolve_template_key(str(cert.ce_type)) for cert in result.eligible}
    assert keys == {"apa", "ny", "nasp", "nbcc", "attendance"}

    by_name = {cert.full_name: cert for cert in result.eligible}
    assert by_name["Riley Okonkwo"].license_number == "012345"
    assert by_name["Renée Chloé D'Amico"].license_number is None
    assert by_name["Devon Blake"].full_name == "Devon Blake"
    assert resolve_template_key(str(by_name["Harper Quinn"].ce_type)) == "attendance"
    assert resolve_template_key(str(by_name["Zoë Ångström"].ce_type)) == "attendance"

    statuses = {entry.status for entry in result.ineligible}
    assert statuses == {
        EligibilityStatus.EXCLUDED,
        EligibilityStatus.ATTENDANCE_INSUFFICIENT,
        EligibilityStatus.NOT_FOUND_IN_ATTENDANCE,
        EligibilityStatus.NAME_MATCH_AMBIGUOUS,
    }
    assert all(entry.name_qualtrics != "Skipped Emptytype" for entry in result.ineligible)

    pdfs = list(tmp_path.glob("*.pdf"))
    assert len(pdfs) == 27
    assert len({path.name for path in pdfs}) == 27
    assert (tmp_path / "ineligibility_report.xlsx").is_file()
    combined = "\n".join(_pdf_text(path) for path in pdfs)
    assert "José Núñez-García" in combined
    assert "Zoë Ångström" in combined
    assert "Siobhán Máire O'Sullivan-Pérez" in combined
    assert "Morgan Hale" not in combined
    renee = next(path for path in pdfs if "Amico" in path.name)
    assert "NY Psychology License" not in _pdf_text(renee)
    for path in pdfs:
        info = subprocess.run(  # noqa: S603
            [_require_tool("pdfinfo"), str(path)],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        ).stdout
        assert re.search(r"^Pages:\s+1$", info, re.MULTILINE), path.name
        assert _PLACEHOLDER_RE.search(_pdf_text(path)) is None

    for path in tmp_path.iterdir():
        path.unlink()
    again = run_pipeline(
        zoom_path=str(_FIXTURES / "v1_zoom.xlsx"),
        qualtrics_path=str(_FIXTURES / "v1_qualtrics.xlsx"),
        title="Mock Ethics Institute",
        training_date=date(2026, 4, 16),
        instructor=_INSTRUCTOR,
        ce_credits=3,
        ce_types=["APA", "NASP", "NY", "NBCC"],
        start_time=_START,
        end_time=_END,
        output_dir=str(tmp_path),
        excluded_names={"Morgan Hale"},
    )
    assert again.errors == []
    assert len(list(tmp_path.glob("*.pdf"))) == 27


def test_bad_zoom_row_is_reported(tmp_path: Path) -> None:
    result = run_pipeline(
        zoom_path=str(_FIXTURES / "v1_zoom_bad_row.xlsx"),
        qualtrics_path=str(_FIXTURES / "v1_qualtrics.xlsx"),
        title="Mock Ethics Institute",
        training_date=date(2026, 4, 16),
        instructor=_INSTRUCTOR,
        ce_credits=3,
        ce_types=["APA"],
        start_time=_START,
        end_time=_END,
        output_dir=str(tmp_path),
    )
    assert result.eligible == []
    assert result.errors
    assert "duration" in result.errors[0].lower()
