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
_XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
_NSMAP = {"w": _W_NS}
_HYPERLINK_INSTR_RE = re.compile(r'^\s*HYPERLINK\s+".*"\s*$')

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
            "NAME": name,
            "Program title": title,
            "Name, Degree": instructor,
            "TIME – TIME ET": f"{time_display} ET",  # noqa: RUF001
            _NASP_DELIVERY_OPTIONS: delivery,
            "X continuing education": f"{credits} continuing education",
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

    Replacements are applied per leaf paragraph (concatenated ``w:t`` runs) so
    tokens split across runs still match. Only runs that cover a match are
    updated, so neighboring bold/underline formatting stays intact. Longer keys
    are applied first.
    """
    ordered = sorted(replacements.items(), key=lambda item: len(item[0]), reverse=True)
    destination.parent.mkdir(parents=True, exist_ok=True)

    with ZipFile(template, "r") as zin, ZipFile(destination, "w", compression=ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            raw = zin.read(info.filename)
            if info.filename.startswith("word/") and info.filename.endswith(".xml"):
                raw = _replace_in_xml(raw, ordered)
            zout.writestr(info, raw)


def _replace_in_xml(
    raw: bytes,
    ordered: list[tuple[str, str]],
) -> bytes:
    root = etree.fromstring(raw)
    paragraphs = root.xpath(".//w:p", namespaces=_NSMAP)
    for paragraph in paragraphs:
        if paragraph.xpath("./descendant::w:p", namespaces=_NSMAP):
            continue
        _replace_in_paragraph(paragraph, ordered)
    _strip_visible_field_instructions(root)
    _strip_highlights(root)
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def _strip_visible_field_instructions(root: etree.ElementBase) -> None:
    for node in root.xpath(".//w:t", namespaces=_NSMAP):
        if node.text and _HYPERLINK_INSTR_RE.match(node.text):
            node.text = ""


def _strip_highlights(root: etree.ElementBase) -> None:
    for highlight in root.xpath(".//w:highlight", namespaces=_NSMAP):
        parent = highlight.getparent()
        if parent is not None:
            parent.remove(highlight)


def _replace_in_paragraph(
    paragraph: etree.ElementBase,
    ordered: list[tuple[str, str]],
) -> None:
    for key, value in ordered:
        if not key:
            continue
        text_nodes = paragraph.xpath(".//w:t", namespaces=_NSMAP)
        if not text_nodes:
            return
        full = "".join((node.text or "") for node in text_nodes)
        starts: list[int] = []
        idx = 0
        while True:
            pos = full.find(key, idx)
            if pos == -1:
                break
            starts.append(pos)
            idx = pos + len(key)
        for start in reversed(starts):
            text_nodes = paragraph.xpath(".//w:t", namespaces=_NSMAP)
            _splice_value(text_nodes, start, start + len(key), value)


def _splice_value(
    text_nodes: list[etree.ElementBase],
    start: int,
    end: int,
    value: str,
) -> None:
    offset = 0
    covering: list[tuple[etree.ElementBase, int]] = []
    for node in text_nodes:
        text = node.text or ""
        node_start = offset
        node_end = offset + len(text)
        offset = node_end
        if node_end <= start or node_start >= end:
            continue
        covering.append((node, node_start))
    if not covering:
        return
    first, first_start = covering[0]
    prefix = (first.text or "")[: start - first_start]
    last, last_start = covering[-1]
    suffix = (last.text or "")[end - last_start :]
    if first is last:
        _set_text(first, prefix + value + suffix)
        return
    _set_text(first, prefix + value)
    for node, _node_start in covering[1:-1]:
        _set_text(node, "")
    _set_text(last, suffix)


def _set_text(node: etree.ElementBase, text: str) -> None:
    node.text = text
    if text[:1].isspace() or text[-1:].isspace():
        node.set(_XML_SPACE, "preserve")
