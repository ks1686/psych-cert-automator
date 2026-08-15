from __future__ import annotations

from typing import TYPE_CHECKING

from src.generator.convert import convert_docx_to_pdf
from src.generator.templates import fill_template, template_path_for

if TYPE_CHECKING:
    from pathlib import Path


def test_convert_docx_to_pdf_writes_sibling_pdf(tmp_path: Path) -> None:
    dest = tmp_path / "filled.docx"
    fill_template(
        template_path_for("APA"),
        dest,
        {
            "NAME": "Jamie Example",
            "TITLE": "Sample Training",
            "COMPLETION DATE:": "COMPLETION DATE: March 20, 2026",
            "CE CREDITS:": "CE CREDITS: 3",
            "LOCATION: Virtual Event": "LOCATION: Virtual Event",
            "FORMAT: Live Webinar": "FORMAT: Live Webinar",
        },
    )
    pdf_path = convert_docx_to_pdf(dest)
    assert pdf_path is not None
    assert pdf_path == dest.with_suffix(".pdf")
    assert pdf_path.is_file()
    assert pdf_path.read_bytes()[:4] == b"%PDF"
    # convert() itself may keep the source; generate_certificate deletes it.
