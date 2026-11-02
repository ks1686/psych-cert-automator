"""Read the first sheet of an .xlsx workbook or a .csv file as plain rows."""

from __future__ import annotations

import csv
import zipfile
import zlib
from pathlib import Path

import openpyxl
from openpyxl.utils.exceptions import InvalidFileException

_EXCEL_SUFFIXES = frozenset({".xlsx", ".xlsm"})
_CSV_SUFFIXES = frozenset({".csv"})

Row = tuple[object, ...]

# What openpyxl can raise for a damaged workbook: a bad zip container, a
# missing part, truncated or invalid XML (ElementTree and lxml both raise
# SyntaxError subclasses), or a corrupt compressed stream.
_DAMAGED_WORKBOOK_ERRORS = (
    InvalidFileException,
    zipfile.BadZipFile,
    KeyError,
    OSError,
    EOFError,
    SyntaxError,
    ValueError,
    TypeError,
    zlib.error,
)


class UnreadableFileError(ValueError):
    """The file exists but is not a readable .xlsx or .csv export."""


def read_rows(filepath: str) -> list[Row]:
    """Return every row of the first worksheet (xlsx) or of the CSV file.

    Raises:
        FileNotFoundError: If *filepath* does not exist.
        UnreadableFileError: If the file is not a readable .xlsx or .csv.
    """
    path = Path(filepath)
    if not path.is_file():
        msg = f"File not found: {filepath}"
        raise FileNotFoundError(msg)
    suffix = path.suffix.lower()
    if suffix in _CSV_SUFFIXES:
        return _read_csv(path)
    if suffix in _EXCEL_SUFFIXES:
        return _read_xlsx(path)
    msg = (
        f"Could not read {path.name}: expected an Excel .xlsx or a .csv export "
        f"(got {suffix or 'no extension'})."
    )
    raise UnreadableFileError(msg)


def _read_xlsx(path: Path) -> list[Row]:
    try:
        workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except _DAMAGED_WORKBOOK_ERRORS as exc:
        msg = f"Could not read {path.name}: it is not a valid Excel .xlsx file."
        raise UnreadableFileError(msg) from exc
    try:
        sheet = workbook.active
        # read_only sheets parse lazily, so damage inside the sheet XML only
        # shows up while iterating.
        rows = None if sheet is None else list(sheet.iter_rows(values_only=True))
    except _DAMAGED_WORKBOOK_ERRORS as exc:
        msg = f"Could not read {path.name}: the Excel file is damaged or incomplete."
        raise UnreadableFileError(msg) from exc
    finally:
        workbook.close()
    if rows is None:
        msg = f"Could not read {path.name}: the workbook has no worksheet."
        raise UnreadableFileError(msg)
    return [tuple(row) for row in rows]


def _read_csv(path: Path) -> list[Row]:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            with path.open(encoding=encoding, newline="") as handle:
                return [
                    tuple(cell if cell.strip() else None for cell in row)
                    for row in csv.reader(handle)
                ]
        except UnicodeDecodeError:
            continue
        except OSError as exc:
            # Permission denied, a sharing lock, or a device error: the file
            # exists but this run cannot read it. Callers promise a clear
            # "could not read" message, never a 500.
            msg = f"Could not read {path.name}: the file could not be opened."
            raise UnreadableFileError(msg) from exc
    msg = f"Could not read {path.name}: the CSV is not UTF-8 or Windows-1252 text."
    raise UnreadableFileError(msg)
