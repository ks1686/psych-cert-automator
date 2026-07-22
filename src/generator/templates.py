"""CE type → Word template resolution and docx placeholder filling."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal
from zipfile import ZIP_DEFLATED, ZipFile

from lxml import etree

TemplateKey = Literal["apa", "ny", "nasp", "attendance"]

_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_NSMAP = {"w": _W_NS}

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TEMPLATES_DIR = _REPO_ROOT / "templates"

_APA_RE = re.compile(r"\bAPA\b|psychologist\s*\(\s*APA\s*\)", re.IGNORECASE)
_NY_RE = re.compile(
    r"\bNY\b|New York|psychologist\s*\(\s*New York\s*\)",
    re.IGNORECASE,
)
_NASP_RE = re.compile(r"\bNASP\b|school psychologist", re.IGNORECASE)

_DEFAULT_VIRTUAL_LOCATION = "Virtual Event"
_DEFAULT_VIRTUAL_FORMAT = "Live Webinar"
_DEFAULT_IN_PERSON_LOCATION = "Rutgers University in Piscataway, NJ"
_DEFAULT_IN_PERSON_FORMAT = "In-Person"
_NASP_VIRTUAL_PHRASE = "via Live Zoom Webinar"
_NASP_DELIVERY_OPTIONS = (
    "via Live Zoom Webinar/at Rutgers University in Piscataway, NJ/City, State"
)


@dataclass(frozen=True, slots=True)
class TemplateRenderContext:
    """Values used to fill a certificate Word template."""

    full_name: str
    training_title: str
    instructor_name: str
    ce_credits: int
    license_number: str | None
    date_display: str
    time_display: str
    is_virtual: bool
    location: str | None


def templates_dir() -> Path:
    """Return the project templates directory."""
    return _TEMPLATES_DIR


def resolve_template_key(ce_type: str) -> TemplateKey:
    """Map a Qualtrics CE type string to a template key.

    Known NY / APA / NASP signals get their dedicated template. Everything else
    (including former BCBA requests) falls back to Certificate of Attendance.
    """
    text = ce_type.strip()
    if not text:
        return "attendance"
    if _APA_RE.search(text):
        return "apa"
    if _NY_RE.search(text):
        return "ny"
    if _NASP_RE.search(text):
        return "nasp"
    return "attendance"


def template_path_for(ce_type: str) -> Path:
    """Return the absolute path to the Word template for ``ce_type``."""
    key = resolve_template_key(ce_type)
    path = _TEMPLATES_DIR / f"{key}.docx"
    if not path.is_file():
        msg = f"Missing certificate template: {path}"
        raise FileNotFoundError(msg)
    return path


def format_training_date(start: date, end: date | None = None) -> str:
    """Format a single date or inclusive start–end range for certificates."""
    if end is None or end == start:
        return f"{start:%B} {start.day}, {start.year}"
    if start.year == end.year and start.month == end.month:
        return f"{start:%B} {start.day}–{end.day}, {start.year}"
    if start.year == end.year:
        return f"{start:%B} {start.day} – {end:%B} {end.day}, {start.year}"
    return f"{start:%B} {start.day}, {start.year} – {end:%B} {end.day}, {end.year}"


def location_and_format(ctx: TemplateRenderContext) -> tuple[str, str]:
    """Resolve Location and Format strings from delivery mode."""
    if ctx.is_virtual:
        return _DEFAULT_VIRTUAL_LOCATION, _DEFAULT_VIRTUAL_FORMAT
    location = (ctx.location or "").strip() or _DEFAULT_IN_PERSON_LOCATION
    return location, _DEFAULT_IN_PERSON_FORMAT


def build_replacements(key: TemplateKey, ctx: TemplateRenderContext) -> dict[str, str]:
    """Build literal string replacements for a specific template."""
    location, fmt = location_and_format(ctx)
    license_value = (ctx.license_number or "").strip()
    title = ctx.training_title.strip()
    name = ctx.full_name.strip()
    instructor = ctx.instructor_name.strip()
    credits = str(ctx.ce_credits)
    time_display = ctx.time_display.strip() or "—"

    if key == "apa":
        return {
            "NAME": name,
            "TITLE": title,
            "COMPLETION DATE:": f"COMPLETION DATE: {ctx.date_display}",
            "CE CREDITS:": f"CE CREDITS: {credits}",
            "LOCATION: Virtual Event": f"LOCATION: {location}",
            "FORMAT: Live Webinar": f"FORMAT: {fmt}",
        }

    if key == "ny":
        license_line = "NY Psychology License #"
        if license_value:
            license_line = f"NY Psychology License # {license_value}"
        return {
            "NAME": name,
            "NY Psychology License #": license_line,
            "TITLE": title,
            "INSTRUCTOR:": f"INSTRUCTOR: {instructor}",
            "COMPLETION DATE:": f"COMPLETION DATE: {ctx.date_display}",
            "CE CREDITS:": f"CE CREDITS: {credits}",
            "LOCATION: Virtual Event": f"LOCATION: {location}",
            "FORMAT: Live Webinar": f"FORMAT: {fmt}",
        }

    if key == "nasp":
        delivery = (
            _NASP_VIRTUAL_PHRASE if ctx.is_virtual else f"at {location}"
        )
        return {
            "This is to certify that NAME has attended": (
                f"This is to certify that {name} has attended"
            ),
            "“Program title”": f"“{title}”",
            '"Program title"': f'"{title}"',
            "presented by Name, Degree": f"presented by {instructor}",
            f"on DATE from TIME – TIME ET {_NASP_DELIVERY_OPTIONS}": (
                f"on {ctx.date_display} from {time_display} ET {delivery}"
            ),
            "X continuing education": f"{credits} continuing education",
            # Header date (standalone paragraph); apply after longer DATE phrases.
            "DATE": ctx.date_display,
        }

    # attendance
    return {
        "NAME": name,
        "TITLE": title,
        "DATE:": f"DATE: {ctx.date_display}",
        "TIME:": f"TIME: {time_display}",
        "Location: Virtual Event": f"Location: {location}",
        "Format: Live Webinar": f"Format: {fmt}",
    }


def fill_template(template: Path, destination: Path, replacements: dict[str, str]) -> None:
    """Copy ``template`` to ``destination`` with literal placeholder replacements.

    Replacements are applied per paragraph (concatenated ``w:t`` runs) so tokens
    split across runs still match. Longer keys are applied first.
    """
    ordered = sorted(replacements.items(), key=lambda item: len(item[0]), reverse=True)
    destination.parent.mkdir(parents=True, exist_ok=True)

    with ZipFile(template, "r") as zin, ZipFile(destination, "w", compression=ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            raw = zin.read(info.filename)
            if info.filename.startswith("word/") and info.filename.endswith(".xml"):
                raw = _replace_in_xml(raw, ordered)
            zout.writestr(info, raw)


def _replace_in_xml(raw: bytes, ordered: list[tuple[str, str]]) -> bytes:
    root = etree.fromstring(raw)
    paragraphs = root.xpath(".//w:p", namespaces=_NSMAP)
    for paragraph in paragraphs:
        _replace_in_paragraph(paragraph, ordered)
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def _replace_in_paragraph(
    paragraph: etree.ElementBase,
    ordered: list[tuple[str, str]],
) -> None:
    text_nodes = paragraph.xpath(".//w:t", namespaces=_NSMAP)
    if not text_nodes:
        return
    full = "".join((node.text or "") for node in text_nodes)
    updated = full
    for key, value in ordered:
        if key in updated:
            updated = updated.replace(key, value)
    if updated == full:
        return
    text_nodes[0].text = updated
    for node in text_nodes[1:]:
        node.text = ""
