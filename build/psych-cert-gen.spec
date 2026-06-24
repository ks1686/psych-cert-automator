# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller onefile spec for the psych-cert-gen FastAPI backend.

Entry point: src/backends/main.py
Output: single console-enabled binary for the target platform.

Generated for the Tauri externalBin pipeline.
See build/build.py for platform-aware binary naming.
"""

from __future__ import annotations

from pathlib import Path

# SPECPATH is provided by PyInstaller when exec()ing the spec file.
# It is the directory containing this spec file.
_PROJECT_ROOT = Path(SPECPATH).resolve().parent  # type: ignore[name-defined]  # noqa: F821

# ──────────────────────────────────── Hidden imports ──────────────────────────────
# Dependencies from pyproject.toml: openpyxl, fpdf2, pydantic, click, pyyaml
# Plus runtime dependencies: uvicorn, fastapi, starlette, anyio, httpx, httpcore

_uvicorn_submodules = [
    "uvicorn.logging",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.flow_control",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.http.httptools_impl",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.protocols.websockets.wsproto_impl",
    "uvicorn.loops.asyncio",
    "uvicorn.loops.auto",
    "uvicorn.loops.uvloop",
    "uvicorn.config",
    "uvicorn.server",
    "uvicorn.workers",
]

_fastapi_submodules = [
    "fastapi",
    "fastapi.datastructures",
    "fastapi.encoders",
    "fastapi.exception_handlers",
    "fastapi.middleware",
    "fastapi.middleware.cors",
    "fastapi.openapi",
    "fastapi.openapi.constants",
    "fastapi.openapi.models",
    "fastapi.openapi.utils",
    "fastapi.param_functions",
    "fastapi.params",
    "fastapi.requests",
    "fastapi.responses",
    "fastapi.routing",
    "fastapi.security",
    "fastapi.security.api_key",
    "fastapi.security.http",
    "fastapi.security.oauth2",
    "fastapi.security.open_id_connect_url",
    "fastapi.types",
    "fastapi.utils",
]

_starlette_submodules = [
    "starlette",
    "starlette.applications",
    "starlette.authentication",
    "starlette.background",
    "starlette.concurrency",
    "starlette.convertors",
    "starlette.datastructures",
    "starlette.endpoints",
    "starlette.exceptions",
    "starlette.formparsers",
    "starlette.middleware",
    "starlette.middleware.base",
    "starlette.middleware.cors",
    "starlette.middleware.errors",
    "starlette.middleware.gzip",
    "starlette.middleware.httpsredirect",
    "starlette.middleware.trustedhost",
    "starlette.middleware.wsgi",
    "starlette.requests",
    "starlette.responses",
    "starlette.routing",
    "starlette.schemas",
    "starlette.status",
    "starlette.templating",
    "starlette.testclient",
    "starlette.types",
    "starlette.websockets",
]

_pydantic_modules = [
    "pydantic",
    "pydantic_core",
    "pydantic_core.core_schema",
    "pydantic.deprecated.decorator",
    "pydantic.json",
    "pydantic.json_schema",
    "pydantic.aliases",
    "pydantic.color",
    "pydantic.config",
    "pydantic.dataclasses",
    "pydantic.datetime_parse",
    "pydantic.errors",
    "pydantic.fields",
    "pydantic.functional_serializers",
    "pydantic.functional_validators",
    "pydantic.main",
    "pydantic.networks",
    "pydantic.types",
    "pydantic.validate_call_decorator",
    "pydantic.v1",
]

_openpyxl_modules = [
    "openpyxl",
    "openpyxl.cell._writer",
    "openpyxl.cell.cell",
    "openpyxl.drawing.spreadsheet_drawing",
    "openpyxl.styles.numbers",
    "openpyxl.utils",
    "openpyxl.utils.datetime",
    "openpyxl.utils.cell",
    "openpyxl.xml",
    "openpyxl.xml.functions",
    "openpyxl.workbook",
    "openpyxl.workbook.workbook",
    "openpyxl.worksheet",
    "openpyxl.worksheet._reader",
    "openpyxl.worksheet.worksheet",
    "openpyxl.reader.excel",
    "openpyxl.writer.excel",
]

_fpdf_modules = [
    "fpdf",
    "fpdf.enums",
    "fpdf.fonts",
    "fpdf.html",
    "fpdf.output",
    "fpdf.template",
    "fpdf.errors",
    "fpdf.drawing",
    "fpdf.line_break",
    "fpdf.table",
    "fpdf.syntax",
    "fpdf.transitions",
]

_async_modules = [
    "anyio._backends._asyncio",
    "anyio._core._eventloop",
    "anyio._core._sockets",
    "anyio._core._streams",
    "anyio._core._synchronization",
    "anyio._core._tasks",
    "anyio._core._testing",
    "anyio.streams",
    "httpcore",
    "httpcore._async",
    "httpcore._sync",
    "httpx",
    "httpx._client",
    "httpx._transports",
]

_additional_modules = [
    "click",
    "click._compat",
    "click.core",
    "click.decorators",
    "click.types",
    "click.utils",
    "yaml",
]

_hidden_imports = (
    _uvicorn_submodules
    + _fastapi_submodules
    + _starlette_submodules
    + _pydantic_modules
    + _openpyxl_modules
    + _fpdf_modules
    + _async_modules
    + _additional_modules
)

# ──────────────────────────────────── Excludes ───────────────────────────────────
_excludes = [
    "matplotlib",
    "scipy",
    "numpy",
    "pandas",
    "tkinter",
    "PyQt5",
    "PyQt6",
    "PySide2",
    "PySide6",
    "IPython",
    "notebook",
    "torch",
    "transformers",
    "tensorflow",
    "jupyter",
    "jupyterlab",
    "PIL",
    "Pillow",
    "cryptography",
]

# ──────────────────────────────────── Analysis ───────────────────────────────────
a = Analysis(
    [str(_PROJECT_ROOT / "src" / "backends" / "main.py")],
    pathex=[str(_PROJECT_ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=_hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=_excludes,
    noarchive=False,
    optimize=0,
)

# ──────────────────────────────────── PYZ ────────────────────────────────────────
pyz = PYZ(a.pure)

# ──────────────────────────────────── EXE ────────────────────────────────────────
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="psych-cert-gen",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
