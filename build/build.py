#!/usr/bin/env python3
"""Build the psych-cert-gen FastAPI backend as a standalone PyInstaller onefile binary.

Produces a platform-specific executable in src-tauri/bin/api/ with a target-triple suffix,
matching the Tauri externalBin configuration.

Usage:
    python build/build.py

Platform target triples:
    aarch64-apple-darwin   — Apple Silicon macOS
    x86_64-apple-darwin    — Intel macOS
    x86_64-pc-windows-msvc — Windows (MSVC)
    x86_64-unknown-linux-gnu — Linux
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Final

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SPEC_FILE: Final[Path] = Path(__file__).resolve().parent / "psych-cert-gen.spec"
_OUTPUT_BASE_DIR: Final[Path] = _PROJECT_ROOT / "src-tauri" / "bin" / "api"
_DIST_DIR: Final[Path] = _PROJECT_ROOT / "dist"
_BUILD_DIR: Final[Path] = _PROJECT_ROOT / "build"
_BINARY_NAME: Final[str] = "psych-cert-gen"

# ──────────────────────────────────── Platform detection ──────────────────────────


def _detect_target_triple() -> str:
    """Detect the target platform triple from the current host.

    Mapping:
        Darwin  + arm64   → aarch64-apple-darwin
        Darwin  + x86_64  → x86_64-apple-darwin
        Windows + AMD64   → x86_64-pc-windows-msvc
        Windows + x86_64  → x86_64-pc-windows-msvc
        Linux   + x86_64  → x86_64-unknown-linux-gnu
        Linux   + aarch64 → aarch64-unknown-linux-gnu
    """
    system = platform.system()
    machine = platform.machine().lower()

    if system == "Darwin":
        if machine in ("arm64", "aarch64"):
            return "aarch64-apple-darwin"
        if machine in ("x86_64", "amd64"):
            return "x86_64-apple-darwin"
    elif system == "Windows":
        if machine in ("amd64", "x86_64", "x64"):
            return "x86_64-pc-windows-msvc"
    elif system == "Linux":
        if machine in ("x86_64", "amd64"):
            return "x86_64-unknown-linux-gnu"
        if machine in ("aarch64", "arm64"):
            return "aarch64-unknown-linux-gnu"

    raise SystemExit(f"Unsupported platform: {system} / {machine}")


def _is_windows(target_triple: str) -> bool:
    return "windows" in target_triple


# ──────────────────────────────────── Validation ──────────────────────────────────


def _validate_entry_point() -> None:
    """Check that the FastAPI entry point exists before building."""
    entry_point = _PROJECT_ROOT / "src" / "backends" / "main.py"
    if not entry_point.exists():
        print(f"[WARN] Entry point not found: {entry_point}")
        print("       The spec file is valid, but the build will fail until the backend exists.")
        print("       This is expected if T2 worker is still building the backend.")
    else:
        print(f"[OK] Entry point found: {entry_point}")


def _check_pyinstaller() -> None:
    """Ensure PyInstaller is importable; install if missing."""
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("[INFO] PyInstaller not found. Installing...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
        print("[OK] PyInstaller installed.")


# ──────────────────────────────────── Build ────────────────────────────────────────


def _run_pyinstaller() -> None:
    """Run PyInstaller with the project spec file."""
    print(f"[BUILD] Running PyInstaller with spec: {_SPEC_FILE}")
    subprocess.check_call(
        [sys.executable, "-m", "PyInstaller", str(_SPEC_FILE)],
        cwd=str(_PROJECT_ROOT),
    )


def _find_binary() -> Path:
    """Locate the built binary in the dist directory (onefile mode)."""
    binary_name = _BINARY_NAME + (".exe" if sys.platform == "win32" else "")
    binary_path = _DIST_DIR / binary_name
    if not binary_path.exists():
        raise FileNotFoundError(
            f"Binary not found at {binary_path}. "
            "Check PyInstaller output for errors."
        )
    return binary_path


def _rename_and_place(binary_path: Path, target_triple: str) -> Path:
    """Rename the binary with the target triple and place it in src-tauri/bin/api/."""
    _OUTPUT_BASE_DIR.mkdir(parents=True, exist_ok=True)

    ext = ".exe" if _is_windows(target_triple) else ""
    final_name = f"{_BINARY_NAME}-{target_triple}{ext}"
    final_path = _OUTPUT_BASE_DIR / final_name

    # Remove existing binary with same name if present
    if final_path.exists():
        final_path.unlink()

    shutil.copy2(binary_path, final_path)
    final_path.chmod(0o755)

    return final_path


# ──────────────────────────────────── Main ─────────────────────────────────────────


def main() -> None:
    """Orchestrate the full build pipeline."""
    target_triple = _detect_target_triple()
    print(f"[INFO] Target platform: {target_triple}")

    _check_pyinstaller()
    _validate_entry_point()

    # Ensure the source directory for the backend exists (for hook discovery)
    backends_dir = _PROJECT_ROOT / "src" / "backends"
    backends_dir.mkdir(parents=True, exist_ok=True)

    # Clean previous build artifacts
    if _DIST_DIR.exists():
        shutil.rmtree(_DIST_DIR)
    pyinstaller_work = _PROJECT_ROOT / "build" / "psych-cert-gen"
    if pyinstaller_work.exists():
        shutil.rmtree(pyinstaller_work)

    _run_pyinstaller()

    binary_path = _find_binary()
    print(f"[OK] Binary built: {binary_path}")

    final_path = _rename_and_place(binary_path, target_triple)
    print(f"[DONE] Binary ready: {final_path}")
    print(f"       Run: {final_path}")
    print(f"       Then: curl http://localhost:8008/health")


if __name__ == "__main__":
    main()
