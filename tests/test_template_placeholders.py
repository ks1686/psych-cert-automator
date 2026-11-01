"""Placeholder replacement must never rewrite text that came from user input.

Each placeholder is replaced exactly once, in a single pass over the
template text. A title that contains placeholder words such as NAME, TITLE,
or DATE must come out exactly as typed.
"""

from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile

import pytest
from lxml import etree
from src.generator.templates import (
    TemplateKey,
    TemplateRenderContext,
    build_replacements,
    fill_template,
    templates_dir,
)

_NSMAP = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
TRICKY_TITLE = "ADHD UPDATE: NAME THAT TITLE BY DATE"
TRICKY_NAME = "Dana TITLE Date"


def _document_text(docx: Path) -> str:
    with ZipFile(docx) as archive:
        root = etree.fromstring(archive.read("word/document.xml"))
    parts: list[str] = []
    for paragraph in root.xpath(".//w:p", namespaces=_NSMAP):
        if paragraph.xpath("./descendant::w:p", namespaces=_NSMAP):
            continue
        parts.append("".join(n.text or "" for n in paragraph.xpath(".//w:t", namespaces=_NSMAP)))
    return "\n".join(parts)


@pytest.mark.parametrize("key", ["apa", "ny", "nasp", "nbcc", "attendance"])
def test_tricky_title_survives_every_template(tmp_path: Path, key: TemplateKey) -> None:
    ctx = TemplateRenderContext(
        full_name=TRICKY_NAME,
        training_title=TRICKY_TITLE,
        instructor_name="Dr. NAME Instructor",
        ce_credits=3,
        license_number="012345",
        date_display="November 2, 2026",
        time_display="9:00 AM - 12:00 PM",
        is_virtual=True,
        location=None,
    )
    dest = tmp_path / f"{key}.docx"
    fill_template(templates_dir() / f"{key}.docx", dest, build_replacements(key, ctx))
    text = _document_text(dest)

    assert TRICKY_TITLE in text
    assert TRICKY_NAME in text
    # The inserted values must not have been fed back into later keys.
    assert "November 2, 2026" in text
    assert text.count(TRICKY_TITLE) == 1
