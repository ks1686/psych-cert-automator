"""Pytest defaults loaded before test modules."""

from __future__ import annotations

import os
from pathlib import Path

# dxpdf follows fontconfig. Without this, Californian FB and Arial Unicode MS
# fall back to whatever serif or sans is installed, and the golden PNGs move.
_FONTCONFIG = Path(__file__).resolve().parent / "fixtures" / "fontconfig" / "fonts.conf"
os.environ["FONTCONFIG_FILE"] = str(_FONTCONFIG)
