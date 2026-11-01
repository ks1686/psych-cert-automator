"""Certificate generation — fill official Word templates, soft-fail PDF convert."""

from __future__ import annotations

import logging
import re
import zlib
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
        try:
            docx_path.unlink(missing_ok=True)
        except OSError:
            logger.warning("Could not delete filled Word document %s", docx_path.name)
        return str(pdf_path.resolve())

    logger.warning(
        "Kept Word document for %s (PDF converter not available)",
        docx_path.name,
    )
    return str(docx_path.resolve())


_PAGE_OBJECT = re.compile(rb"/Type\s*/Page(?![a-zA-Z])")
_OBJECT_STREAM = re.compile(
    rb"<<(?:(?!>>).)*?/Type\s*/ObjStm(?:(?!>>).)*?>>\s*stream\r?\n", re.DOTALL
)
_PAGES_COUNT = re.compile(
    rb"/Type\s*/Pages\b[^>]*?/Count\s+(\d+)|/Count\s+(\d+)[^>]*?/Type\s*/Pages\b"
)

# Scripts the certificate fonts render: Latin (with extensions), Greek,
# Cyrillic, combining marks, and common punctuation and symbols.
_SUPPORTED_RANGES: tuple[tuple[int, int], ...] = (
    (0x0000, 0x024F),
    (0x0250, 0x02FF),
    (0x0300, 0x036F),
    (0x0370, 0x03FF),
    (0x0400, 0x04FF),
    (0x1E00, 0x1EFF),
    (0x2000, 0x206F),
    (0x20A0, 0x20CF),
    (0x2100, 0x214F),
)


def pdf_page_count(pdf_path: Path) -> int | None:
    """Return the page count of a PDF, or ``None`` if it cannot be read cheaply."""
    try:
        data = pdf_path.read_bytes()
    except OSError:
        return None
    # PDF 1.5+ writers may pack the page objects into compressed object
    # streams, so search their contents too.
    data += b"".join(_object_stream_contents(data))
    pages = len(_PAGE_OBJECT.findall(data))
    if pages:
        return pages
    counts = [int(a or b) for a, b in _PAGES_COUNT.findall(data)]
    return max(counts) if counts else None


def _object_stream_contents(data: bytes) -> list[bytes]:
    """Inflate every Flate-compressed /ObjStm stream (others are skipped)."""
    contents: list[bytes] = []
    for match in _OBJECT_STREAM.finditer(data):
        if b"FlateDecode" not in match.group(0):
            continue
        end = data.find(b"endstream", match.end())
        if end == -1:
            continue
        try:
            contents.append(zlib.decompressobj().decompress(data[match.end() : end]))
        except zlib.error:
            continue
    return contents


def _unsupported_characters(text: str) -> str:
    seen: list[str] = []
    for char in text:
        code = ord(char)
        if any(low <= code <= high for low, high in _SUPPORTED_RANGES):
            continue
        if char not in seen:
            seen.append(char)
    return "".join(seen)


def certificate_warnings(output: CertificateOutput, generated_path: str) -> list[str]:
    """Return problems a person should check before sending this certificate.

    Flags text in scripts the certificate fonts may not contain (for example
    Chinese, Japanese, or Korean characters, which PDF conversion can drop
    silently) and PDFs that spill onto a second page.
    """
    warnings: list[str] = []
    for label, value in (
        ("name", output.full_name),
        ("title", output.training_title),
        ("instructor", output.instructor_name),
    ):
        missing = _unsupported_characters(value)
        if missing:
            warnings.append(
                f"{output.full_name} ({output.ce_type}): the {label} {value!r} uses "
                f"characters the certificate font may not have ({missing}); "
                "check the PDF or edit the Word document by hand.",
            )
    path = Path(generated_path)
    if path.suffix.lower() == ".pdf" and path.is_file():
        pages = pdf_page_count(path)
        if pages is not None and pages > 1:
            warnings.append(
                f"{output.full_name} ({output.ce_type}): {path.name} has {pages} pages "
                "(expected 1); a long name or title probably wrapped. Check it before sending.",
            )
    return warnings


_GENERATED_SUFFIXES = (".pdf", ".docx")


def _avoid_existing_files(stems: list[str], out_dir: Path) -> list[str]:
    """Suffix ``_2``, ``_3``... onto stems whose files already exist on disk."""

    def taken(stem: str) -> bool:
        return stem in chosen or any(
            (out_dir / f"{stem}{suffix}").exists() for suffix in _GENERATED_SUFFIXES
        )

    chosen: set[str] = set(stems)
    result: list[str] = []
    for stem in stems:
        chosen.discard(stem)
        candidate, n = stem, 2
        while taken(candidate):
            candidate = f"{stem}_{n}"
            n += 1
        chosen.add(candidate)
        result.append(candidate)
    return result


def generate_all(
    requests: list[CertificateOutput],
    output_dir: str,
    *,
    options: CertificateRenderOptions | None = None,
) -> list[str]:
    """Generate certificates for a batch of eligible outputs.

    Assigns unique basenames within the batch so identical last names (or the
    same person requesting multiple CE types) do not overwrite each other, and
    skips names already used by a ``.pdf`` or ``.docx`` in ``output_dir`` so a
    second run into the same folder never overwrites an earlier certificate.

    Args:
        requests: One ``CertificateOutput`` per certificate.
        output_dir: Directory where generated files are written.
        options: Shared delivery / schedule settings for the batch.

    Returns:
        Absolute paths to generated PDF or DOCX files, in request order.
    """
    stems = _avoid_existing_files(allocate_unique_basenames(requests), Path(output_dir))
    results: list[str] = []
    for req, stem in zip(requests, stems, strict=True):
        results.append(
            generate_certificate(req, output_dir, options=options, basename=stem)
        )
    return results
