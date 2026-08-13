"""Tests for Word-template certificate mapping and filename conventions."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from zipfile import ZipFile

from lxml import etree
from src.generator.certificate import CertificateRenderOptions, generate_certificate
from src.generator.templates import (
    TemplateRenderContext,
    _replace_in_xml,
    build_replacements,
    fill_template,
    format_training_date,
    resolve_template_key,
    template_path_for,
)
from src.models.certificate import CertificateOutput
from src.models.training import CEType

_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_NSMAP = {"w": _W_NS}


def _leaf_paragraph_texts(docx: Path) -> list[str]:
    """Return concatenated text of paragraphs that do not wrap nested paragraphs."""
    with ZipFile(docx) as archive:
        root = etree.fromstring(archive.read("word/document.xml"))
    texts: list[str] = []
    for paragraph in root.xpath(".//w:p", namespaces=_NSMAP):
        nested = paragraph.xpath("./descendant::w:p", namespaces=_NSMAP)
        if nested:
            continue
        full = "".join(
            node.text or ""
            for node in paragraph.xpath(".//w:t", namespaces=_NSMAP)
        )
        if full.strip():
            texts.append(full)
    return texts


def test_resolve_template_key_maps_known_types() -> None:
    assert resolve_template_key("Psychologist (APA)") == "apa"
    assert resolve_template_key("APA") == "apa"
    assert resolve_template_key("Psychologist (New York)") == "ny"
    assert resolve_template_key("NY") == "ny"
    assert resolve_template_key("NASP") == "nasp"
    assert resolve_template_key("BCBA") == "attendance"
    assert resolve_template_key("Something Else") == "attendance"


def test_template_files_exist() -> None:
    for ce in ("APA", "NY", "NASP", "Other"):
        path = template_path_for(ce)
        assert path.is_file()
        assert path.suffix == ".docx"


def test_output_filename_pattern() -> None:
    out = CertificateOutput(
        full_name="Jessica Benas",
        ce_type=CEType("APA"),
        ce_credits=3,
        training_title="Ethics",
        training_date=date(2026, 3, 20),
        instructor_name="Dr. Jane Smith",
        license_number=None,
        issue_date=date(2026, 3, 21),
    )
    assert out.output_basename == "Benas_CECertificate_Smith_3.20.26"
    assert out.output_filename == "Benas_CECertificate_Smith_3.20.26.pdf"


def test_output_filename_sanitizes_at_sign() -> None:
    out = CertificateOutput(
        full_name="Pat O@Brien",
        ce_type=CEType("APA"),
        ce_credits=1,
        training_title="T",
        training_date=date(2026, 1, 2),
        instructor_name="Alex",
        license_number=None,
        issue_date=date(2026, 1, 2),
    )
    assert "@" not in out.output_filename
    assert out.output_basename.startswith("O_Brien_CECertificate_")
    assert out.output_basename.endswith("_1.2.26")
    assert "1_2_26" not in out.output_basename


def test_allocate_unique_basenames_disambiguates_same_last_name() -> None:
    from src.models.certificate import allocate_unique_basenames

    shared = dict(
        ce_credits=3,
        training_title="T",
        training_date=date(2026, 3, 20),
        instructor_name="Dr. Jane Smith",
        license_number=None,
        issue_date=date(2026, 3, 21),
    )
    outputs = [
        CertificateOutput(full_name="Alice Jones", ce_type=CEType("APA"), **shared),
        CertificateOutput(full_name="Bob Jones", ce_type=CEType("APA"), **shared),
        CertificateOutput(full_name="Alice Jones", ce_type=CEType("NASP"), **shared),
    ]
    stems = allocate_unique_basenames(outputs)
    assert len(stems) == len(set(stems))
    assert stems[0] == "Jones_CECertificate_Smith_3.20.26"
    assert "Bob" in stems[1] or stems[1].endswith("_APA") or stems[1] != stems[0]
    assert stems[2] != stems[0]


def test_allocate_unique_basenames_identical_full_names() -> None:
    from src.models.certificate import allocate_unique_basenames

    shared = dict(
        ce_type=CEType("APA"),
        ce_credits=3,
        training_title="T",
        training_date=date(2026, 3, 20),
        instructor_name="Dr. Pat Lee",
        license_number=None,
        issue_date=date(2026, 3, 21),
    )
    outputs = [
        CertificateOutput(full_name="Sam Sam", **shared),
        CertificateOutput(full_name="Sam Sam", **shared),
    ]
    stems = allocate_unique_basenames(outputs)
    assert stems[0] != stems[1]
    assert stems[0] == "Sam_CECertificate_Lee_3.20.26"


def test_format_training_date_range() -> None:
    assert format_training_date(date(2026, 3, 18), date(2026, 3, 20)) == (
        "March 18–20, 2026"
    )
    assert format_training_date(date(2026, 3, 20)) == "March 20, 2026"


def test_generate_certificate_writes_filled_docx(tmp_path: Path) -> None:
    out = CertificateOutput(
        full_name="Jamie Example",
        ce_type=CEType("Psychologist (APA)"),
        ce_credits=3,
        training_title="Sample Training",
        training_date=date(2026, 3, 20),
        instructor_name="Dr. Pat Instructor",
        license_number=None,
        issue_date=date(2026, 3, 21),
    )
    path = Path(
        generate_certificate(
            out,
            str(tmp_path),
            options=CertificateRenderOptions(is_virtual=True),
        )
    )
    assert path.exists()
    # Soft-fail may leave .docx when PDF tools are missing.
    assert path.suffix.lower() in {".pdf", ".docx"}
    docx = path if path.suffix.lower() == ".docx" else path.with_suffix(".docx")
    assert docx.is_file()
    with ZipFile(docx) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")
    assert "Jamie Example" in xml
    assert "Sample Training" in xml
    assert ">NAME<" not in xml


def test_replace_does_not_merge_nested_textbox_into_parent_run() -> None:
    raw = (
        b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        b"<w:body><w:p>"
        b"<w:r><w:t>Letterhead</w:t></w:r>"
        b"<w:r><w:drawing><w:txbxContent>"
        b"<w:p><w:r><w:t>NAME</w:t></w:r></w:p>"
        b"</w:txbxContent></w:drawing></w:r>"
        b"</w:p></w:body></w:document>"
    )
    updated = etree.fromstring(_replace_in_xml(raw, [("NAME", "Sasan Haghani")]))
    parent, nested = updated.xpath(".//w:p", namespaces=_NSMAP)
    parent_text = "".join(parent.xpath("./w:r/w:t/text()", namespaces=_NSMAP))
    nested_text = "".join(nested.xpath(".//w:t/text()", namespaces=_NSMAP))
    assert parent_text == "Letterhead"
    assert nested_text == "Sasan Haghani"


def test_replace_only_updates_placeholder_run() -> None:
    raw = (
        b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        b"<w:body><w:p>"
        b"<w:r><w:t>This is to certify that </w:t></w:r>"
        b'<w:r><w:rPr><w:b/><w:u w:val="single"/></w:rPr><w:t>NAME</w:t></w:r>'
        b"<w:r><w:t> has attended </w:t></w:r>"
        b"<w:r><w:rPr><w:b/></w:rPr><w:t>Rutgers.</w:t></w:r>"
        b"</w:p></w:body></w:document>"
    )
    updated = etree.fromstring(_replace_in_xml(raw, [("NAME", "Sasan Haghani")]))
    runs = updated.xpath(".//w:r", namespaces=_NSMAP)
    texts = ["".join(run.xpath(".//w:t/text()", namespaces=_NSMAP)) for run in runs]
    assert texts == [
        "This is to certify that ",
        "Sasan Haghani",
        " has attended ",
        "Rutgers.",
    ]
    name_rpr = runs[1].find(f"{{{_W_NS}}}rPr")
    assert name_rpr is not None
    assert name_rpr.find(f"{{{_W_NS}}}b") is not None
    school_rpr = runs[3].find(f"{{{_W_NS}}}rPr")
    assert school_rpr is not None
    assert school_rpr.find(f"{{{_W_NS}}}b") is not None


def test_fill_apa_keeps_name_in_template_textbox(tmp_path: Path) -> None:
    dest = tmp_path / "filled.docx"
    fill_template(
        template_path_for("APA"),
        dest,
        {
            "NAME": "Sasan Haghani",
            "TITLE": "Ethics in School Psychology",
            "COMPLETION DATE:": "COMPLETION DATE: March 20, 2026",
            "CE CREDITS:": "CE CREDITS: 3",
            "LOCATION: Virtual Event": "LOCATION: Virtual Event",
            "FORMAT: Live Webinar": "FORMAT: Live Webinar",
        },
    )
    drawing_ns = {
        **_NSMAP,
        "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    }
    with ZipFile(dest) as archive:
        root = etree.fromstring(archive.read("word/document.xml"))
    anchored = [
        "".join(node.text or "" for node in anchor.xpath(".//w:t", namespaces=_NSMAP)).strip()
        for anchor in root.xpath(".//wp:anchor", namespaces=drawing_ns)
    ]
    assert "Sasan Haghani" in anchored
    leaves = _leaf_paragraph_texts(dest)
    assert "152 Frelinghuysen Road" in {text.strip() for text in leaves}
    assert "This is to certify that" in {text.strip() for text in leaves}


def test_fill_nasp_preserves_inline_bold_and_strips_highlight(tmp_path: Path) -> None:
    dest = tmp_path / "filled.docx"
    ctx = TemplateRenderContext(
        full_name="Sasan Haghani",
        training_title="Ethics in School Psychology",
        instructor_name="Dr. Jane Smith",
        ce_credits=3,
        license_number=None,
        date_display="March 20, 2026",
        time_display="9:00 AM – 12:00 PM",  # noqa: RUF001
        is_virtual=True,
        location=None,
    )
    fill_template(template_path_for("NASP"), dest, build_replacements("nasp", ctx))
    with ZipFile(dest) as archive:
        root = etree.fromstring(archive.read("word/document.xml"))
    w_b = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}b"
    w_u = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}u"
    w_rpr = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}rPr"
    name_bold_underline = False
    school_bold = False
    for run in root.xpath(".//w:r", namespaces=_NSMAP):
        text = "".join(run.xpath(".//w:t/text()", namespaces=_NSMAP))
        rpr = run.find(w_rpr)
        has_b = rpr is not None and rpr.find(w_b) is not None
        has_u = rpr is not None and rpr.find(w_u) is not None
        if text == "Sasan Haghani" and has_b and has_u:
            name_bold_underline = True
        if "Rutgers Graduate School of Applied and Professional Psychology." in text and has_b:
            school_bold = True
    assert name_bold_underline
    assert school_bold
    highlights = root.xpath(".//w:highlight", namespaces=_NSMAP)
    assert highlights == []


def test_fill_attendance_strips_visible_hyperlink_field_text(tmp_path: Path) -> None:
    dest = tmp_path / "filled.docx"
    fill_template(
        template_path_for("Certificate of Attendance"),
        dest,
        {
            "NAME": "Sasan Haghani",
            "TITLE": "Ethics in School Psychology",
            "DATE:": "DATE: March 20, 2026",
            "TIME:": "TIME: 9:00 AM - 12:00 PM",
            "Location: Virtual Event": "Location: Virtual Event",
            "Format: Live Webinar": "Format: Live Webinar",
        },
    )
    with ZipFile(dest) as archive:
        xml = archive.read("word/document.xml").decode()
    assert "HYPERLINK" not in xml
    assert "jbenas@rutgers.edu" in xml
