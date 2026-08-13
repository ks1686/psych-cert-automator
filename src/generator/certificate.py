"""Certificate generation — fill official Word templates, soft-fail PDF convert."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, time
from pathlib import Path

from src.generator.convert import convert_docx_to_pdf
from src.generator.templates import (
    TemplateRenderContext,
    build_replacements,
    fill_template,
    format_training_date,
    resolve_template_key,
    template_path_for,
)
from src.models.certificate import CertificateOutput, allocate_unique_basenames

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CertificateRenderOptions:
    """Delivery / schedule options that affect template placeholders."""

    is_virtual: bool = True
    location: str | None = None
    end_date: date | None = None
    session_start: time | None = None
    session_end: time | None = None


def _format_clock(value: time | None) -> str:
    if value is None:
        return ""
    hour_12 = value.hour % 12 or 12
    suffix = "AM" if value.hour < 12 else "PM"
    return f"{hour_12}:{value.minute:02d} {suffix}"


def _time_display(options: CertificateRenderOptions) -> str:
    start = _format_clock(options.session_start)
    end = _format_clock(options.session_end)
    if start and end:
        return f"{start} – {end}"
    return start or end


def generate_certificate(
    output: CertificateOutput,
    output_dir: str,
    *,
    options: CertificateRenderOptions | None = None,
    basename: str | None = None,
) -> str:
    """Generate one certificate from the official Word template for its CE type.

    Writes a filled ``.docx``. Converts to PDF with bundled ``dxpdf`` (LibreOffice
    or Microsoft Word as fallback) and returns the PDF path. If conversion fails,
    returns the ``.docx`` path and logs a warning.

    Args:
        output: Fully populated certificate data.
        output_dir: Directory where files are written.
        options: Optional delivery / multi-day render settings.
        basename: Optional unique filename stem (without extension). Defaults
            to ``output.output_basename``.

    Returns:
        Absolute path to the generated PDF or DOCX file.
    """
    render = options or CertificateRenderOptions()
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    key = resolve_template_key(str(output.ce_type))
    template = template_path_for(str(output.ce_type))
    date_display = format_training_date(output.training_date, render.end_date)
    ctx = TemplateRenderContext(
        full_name=output.full_name,
        training_title=output.training_title,
        instructor_name=output.instructor_name,
        ce_credits=output.ce_credits,
        license_number=output.license_number,
        date_display=date_display,
        time_display=_time_display(render),
        is_virtual=render.is_virtual,
        location=render.location,
    )
    replacements = build_replacements(key, ctx)

    stem = basename or output.output_basename
    docx_path = out_dir / f"{stem}.docx"
    fill_template(template, docx_path, replacements)

    pdf_path = convert_docx_to_pdf(docx_path)
    if pdf_path is not None:
        return str(pdf_path.resolve())

    logger.warning(
        "Kept Word document for %s (PDF converter not available)",
        docx_path.name,
    )
    return str(docx_path.resolve())


def generate_all(
    requests: list[CertificateOutput],
    output_dir: str,
    *,
    options: CertificateRenderOptions | None = None,
) -> list[str]:
    """Generate certificates for a batch of eligible outputs.

    Assigns unique basenames within the batch so identical last names (or the
    same person requesting multiple CE types) do not overwrite each other.

    Args:
        requests: One ``CertificateOutput`` per certificate.
        output_dir: Directory where generated files are written.
        options: Shared delivery / schedule settings for the batch.

    Returns:
        Absolute paths to generated PDF or DOCX files, in request order.
    """
    stems = allocate_unique_basenames(requests)
    results: list[str] = []
    for req, stem in zip(requests, stems, strict=True):
        results.append(
            generate_certificate(req, output_dir, options=options, basename=stem)
        )
    return results
