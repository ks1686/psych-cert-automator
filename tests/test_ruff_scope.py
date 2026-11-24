"""Regression guard for ruff's product-tree scope."""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SKILL = ".cursor/skills/verify-psych-cert-gen"
_PRODUCT_DIRS = ("src", "tests")
_PRODUCT_FILES = ("certgen.py",)


def _ruff_settings() -> dict[str, object]:
    with (_ROOT / "pyproject.toml").open("rb") as handle:
        data = tomllib.load(handle)
    tool = data["tool"]
    assert isinstance(tool, dict)
    ruff = tool["ruff"]
    assert isinstance(ruff, dict)
    return ruff


def _excluded_patterns() -> list[str]:
    ruff = _ruff_settings()
    patterns: list[str] = []
    for key in ("extend-exclude", "exclude"):
        raw = ruff.get(key, [])
        if isinstance(raw, list):
            patterns.extend(str(item) for item in raw)
    return patterns


def _checked_files() -> list[Path]:
    completed = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--show-files"],
        cwd=_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    root = _ROOT.resolve()
    files: list[Path] = []
    for line in completed.stdout.splitlines():
        if not line.strip():
            continue
        path = Path(line)
        try:
            files.append(path.resolve().relative_to(root))
        except ValueError:
            files.append(path)
    return files


def test_ruff_src_includes_product_tree() -> None:
    src = _ruff_settings().get("src", [])
    assert isinstance(src, list)
    for directory in _PRODUCT_DIRS:
        assert directory in src


def test_ruff_excludes_verification_skill_not_product_tree() -> None:
    patterns = _excluded_patterns()
    assert _SKILL in patterns
    for path in (*_PRODUCT_DIRS, *_PRODUCT_FILES):
        assert path not in patterns


def test_ruff_check_covers_product_tree_and_skips_skill() -> None:
    relative = {path.as_posix() for path in _checked_files()}
    for directory in _PRODUCT_DIRS:
        assert any(path == directory or path.startswith(f"{directory}/") for path in relative)
    for name in _PRODUCT_FILES:
        assert name in relative
    assert not any(path == _SKILL or path.startswith(f"{_SKILL}/") for path in relative)


def test_ci_ruff_step_uses_configured_tree() -> None:
    workflow = (_ROOT / ".github/workflows/test.yml").read_text(encoding="utf-8")
    assert "uv run ruff check" in workflow
    assert "src/pipeline.py" not in workflow
