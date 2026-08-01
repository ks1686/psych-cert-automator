"""Best-effort Word → PDF conversion (LibreOffice / Microsoft Word)."""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

# Cross-platform: PATH names first, then common absolute install locations.
_LIBREOFFICE_CANDIDATES = (
    "soffice",
    "soffice.exe",
    "libreoffice",
    # macOS
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    # Linux
    "/usr/bin/soffice",
    "/usr/bin/libreoffice",
    "/usr/local/bin/soffice",
    "/snap/bin/libreoffice",
    # Windows (typical install roots)
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
)


def convert_docx_to_pdf(docx_path: Path) -> Path | None:
    """Convert ``docx_path`` to a sibling PDF when a converter is available.

    Tries LibreOffice/soffice first, then macOS Microsoft Word via AppleScript.
    Returns the PDF path on success, or ``None`` if conversion is unavailable
    or fails (caller should keep the ``.docx``).
    """
    docx_path = docx_path.resolve()
    if not docx_path.is_file() or docx_path.suffix.lower() != ".docx":
        return None

    pdf_path = docx_path.with_suffix(".pdf")
    if _convert_with_libreoffice(docx_path, pdf_path):
        return pdf_path
    if _convert_with_mac_word(docx_path, pdf_path):
        return pdf_path
    logger.warning(
        "PDF conversion unavailable for %s; keeping Word document",
        docx_path.name,
    )
    return None


def _convert_with_libreoffice(docx_path: Path, pdf_path: Path) -> bool:
    soffice = _find_libreoffice()
    if soffice is None:
        return False
    out_dir = docx_path.parent
    try:
        completed = subprocess.run(
            [
                soffice,
                "--headless",
                "--nologo",
                "--nolockcheck",
                "--convert-to",
                "pdf",
                "--outdir",
                str(out_dir),
                str(docx_path),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("LibreOffice conversion failed: %s", exc)
        return False
    if completed.returncode != 0:
        logger.warning(
            "LibreOffice exited %s: %s",
            completed.returncode,
            (completed.stderr or completed.stdout or "").strip(),
        )
        return False
    return pdf_path.is_file()


def _find_libreoffice() -> str | None:
    for candidate in _LIBREOFFICE_CANDIDATES:
        path = Path(candidate)
        if path.is_file():
            return str(path)
        found = shutil.which(candidate)
        if found:
            return found
    return None


def _convert_with_mac_word(docx_path: Path, pdf_path: Path) -> bool:
    word_app = Path("/Applications/Microsoft Word.app")
    if not word_app.is_dir():
        return False
    # Pass paths via argv — never interpolate into AppleScript source.
    script = """
on run argv
  set docxPath to item 1 of argv
  set pdfPath to item 2 of argv
  tell application "Microsoft Word"
    set theDoc to open POSIX file docxPath
    set outPath to POSIX file pdfPath
    save as theDoc file name outPath file format format PDF
    close theDoc saving no
  end tell
end run
"""
    try:
        completed = subprocess.run(
            ["osascript", "-e", script, str(docx_path), str(pdf_path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("Word conversion failed: %s", exc)
        return False
    if completed.returncode != 0:
        logger.warning(
            "Word AppleScript exited %s: %s",
            completed.returncode,
            (completed.stderr or completed.stdout or "").strip(),
        )
        return False
    return pdf_path.is_file()
