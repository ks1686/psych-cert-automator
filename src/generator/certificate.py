"""PDF certificate generation — pure-Python via ``fpdf2`` (zero external deps)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from fpdf import FPDF

if TYPE_CHECKING:
    from datetime import date

    from src.models.certificate import CertificateOutput

# ── Layout constants ─────────────────────────────────────────────────────────────
_PAGE_W, _PAGE_H = 279.4, 215.9  # Letter landscape (mm)
_MARGIN = 15.0
_BORDER_INSET = 8.0
_INNER_W = _PAGE_W - 2 * _MARGIN
_INNER_H = _PAGE_H - 2 * _MARGIN
_BORDER_W = _PAGE_W - 2 * _BORDER_INSET
_BORDER_H = _PAGE_H - 2 * _BORDER_INSET

_FONT_TITLE = ("Helvetica", "B", 26)
_FONT_NAME = ("Helvetica", "B", 22)
_FONT_BODY = ("Helvetica", "", 14)
_FONT_DETAIL = ("Helvetica", "", 12)
_FONT_SIGNATURE = ("Helvetica", "", 11)

_Y = _MARGIN + 10  # starting Y position, advances as we draw


def _format_date(d: date) -> str:
    """Format a date like 'March 20, 2026' (no leading zero on day)."""
    return f"{d:%B} {d.day}, {d.year}"


def _text_line(pdf: FPDF, text: str, family: str, style: str, size: int) -> None:
    """Draw a centered line of text and advance Y."""
    pdf.set_font(family, style, size)
    _ = pdf.cell(_INNER_W, 8, text, align="C", new_x="LMARGIN", new_y="NEXT")


def _vspace(pdf: FPDF, mm: float) -> None:
    """Add vertical space."""
    pdf.ln(mm)


def _draw_border(pdf: FPDF) -> None:
    """Draw a double-line decorative border."""
    pdf.set_line_width(0.4)
    pdf.rect(_BORDER_INSET, _BORDER_INSET, _BORDER_W, _BORDER_H)
    pdf.set_line_width(0.2)
    inset2 = _BORDER_INSET + 2
    pdf.rect(inset2, inset2, _BORDER_W - 4, _BORDER_H - 4)


def _draw_signature_block(pdf: FPDF) -> None:
    """Draw instructor signature line and date on the same row."""
    y_sig = pdf.get_y() + 12
    left_x = _MARGIN + 20
    right_x = _MARGIN + _INNER_W - 80

    pdf.set_font(*_FONT_SIGNATURE)
    _ = pdf.line(left_x, y_sig, left_x + 70, y_sig)
    _ = pdf.set_xy(left_x, y_sig + 2)
    _ = pdf.cell(70, 5, "Instructor Signature", align="C")

    _ = pdf.line(right_x, y_sig, right_x + 60, y_sig)
    _ = pdf.set_xy(right_x, y_sig + 2)
    _ = pdf.cell(60, 5, "Date", align="C")


def generate_certificate(
    output: CertificateOutput,
    output_dir: str,
) -> str:
    """Generate a single PDF certificate from a ``CertificateOutput``.

    Renders a professional landscape certificate with double border, the
    recipient's name prominently centered, training details, CE type/credits,
    optional license number, and a signature block.

    Args:
        output: Fully populated certificate data.
        output_dir: Directory where the PDF is written.

    Returns:
        Absolute path to the generated PDF file.
    """
    pdf = FPDF(orientation="L", unit="mm", format="Letter")
    pdf.set_auto_page_break(auto=False)
    pdf.add_page()

    # ── Border ──
    _draw_border(pdf)
    _vspace(pdf, 8)

    # ── Title ──
    _text_line(pdf, "Certificate of Completion", *_FONT_TITLE)
    _vspace(pdf, 2)
    _ = pdf.set_draw_color(0)
    _ = pdf.set_line_width(0.3)
    mid_x = _MARGIN + _INNER_W / 2
    _ = pdf.line(mid_x - 40, pdf.get_y(), mid_x + 40, pdf.get_y())
    _vspace(pdf, 6)

    # ── Body ──
    _text_line(pdf, "This certifies that", *_FONT_BODY)
    _vspace(pdf, 4)

    _text_line(pdf, output.full_name, *_FONT_NAME)
    _vspace(pdf, 4)

    credits_text = (
        f"has successfully completed {output.ce_credits}"
        + " Continuing Education credit hour"
        + ("s" if output.ce_credits != 1 else "")
        + f" in {output.ce_type}"
    )
    _text_line(pdf, credits_text, *_FONT_BODY)
    _vspace(pdf, 8)

    # ── Training details ──
    _text_line(pdf, f"Training:  {output.training_title}", *_FONT_DETAIL)
    _vspace(pdf, 2)
    _text_line(
        pdf,
        f"Date:  {_format_date(output.training_date)}",
        *_FONT_DETAIL,
    )
    _vspace(pdf, 2)
    _text_line(
        pdf,
        f"Instructor:  {output.instructor_name}",
        *_FONT_DETAIL,
    )

    if output.license_number:
        _vspace(pdf, 2)
        _text_line(
            pdf,
            f"License / Certificate #:  {output.license_number}",
            *_FONT_DETAIL,
        )

    _vspace(pdf, 4)
    _text_line(
        pdf,
        f"Issued:  {_format_date(output.issue_date)}",
        *_FONT_DETAIL,
    )

    # ── Signature block ──
    _draw_signature_block(pdf)

    # ── Save ──
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    filepath = out_dir / output.output_filename
    pdf.output(str(filepath))
    return str(filepath.resolve())


def generate_all(
    requests: list[CertificateOutput],
    output_dir: str,
) -> list[str]:
    """Generate PDFs for a batch of certificate requests.

    Args:
        requests: One ``CertificateOutput`` per certificate to generate.
        output_dir: Directory where all generated PDFs are written.

    Returns:
        List of absolute paths to the generated PDFs, in order of *requests*.
    """
    results: list[str] = []
    for req in requests:
        pdf_path = generate_certificate(req, output_dir)
        results.append(pdf_path)
    return results
