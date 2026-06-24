"""Session configuration model — wraps training metadata with file paths and persistence."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from src.models.training import TrainingMetadata  # noqa: TC001

_PATH_FIELDS: tuple[str, ...] = (
    "zoom_path",
    "qualtrics_path",
    "overrides_path",
    "output_dir",
)


def _make_relative(path_str: str, base_dir: Path) -> str:
    """Convert an absolute path to a relative path with respect to *base_dir*.

    If the path is already relative it is returned unchanged.
    """
    if Path(path_str).is_absolute():
        return os.path.relpath(path_str, str(base_dir))
    return path_str


def _make_absolute(rel_path: str, base_dir: Path) -> str:
    """Resolve a relative path against *base_dir* to produce an absolute path.

    If the path is already absolute it is returned unchanged (but still
    normalised so ``..`` components are collapsed).
    """
    if rel_path and not Path(rel_path).is_absolute():
        return os.path.normpath(str(base_dir / rel_path))
    return os.path.normpath(rel_path)


_ERR_BAD_JSON_ROOT = "Session JSON file does not contain a JSON object"


class SessionConfig(BaseModel):
    """A saved certificate-generation session.

    Composes ``TrainingMetadata`` with file paths for input data and output
    directory, plus a version stamp.  Supports JSON round-trip persistence
    with automatic relative-path conversion so session files remain portable.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    metadata: TrainingMetadata
    """Training metadata bundled into the session."""

    zoom_path: str | None = None
    """Path to the Zoom attendance report (may be relative to session file)."""

    qualtrics_path: str | None = None
    """Path to the Qualtrics CE survey export (may be relative to session file)."""

    overrides_path: str | None = None
    """Path to a manual name-matching overrides file (may be relative to session file)."""

    output_dir: str = "./output"
    """Directory where generated certificates are written (may be relative to session file)."""

    saved_at: datetime = Field(default_factory=datetime.now)
    """Timestamp when the session was last saved."""

    version: str = "1.0"
    """Schema version for forward-compatibility."""

    # ── persistence ──────────────────────────────────────────────────────

    def save(self, path: Path) -> None:
        """Serialize this session to *path* as JSON with relative paths.

        Absolute paths in ``zoom_path``, ``qualtrics_path``,
        ``overrides_path``, and ``output_dir`` are converted to relative
        paths (based on the directory that contains *path*) before writing.
        """
        session_dir = path.parent.absolute()
        data = self.model_dump(mode="json")
        for field_name in _PATH_FIELDS:
            value = data.get(field_name)
            if isinstance(value, str) and value:
                data[field_name] = _make_relative(value, session_dir)
        _ = path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> SessionConfig:
        """Deserialize a session from *path*, resolving relative paths.

        Relative paths in the stored JSON are resolved against the
        directory that contains *path*.
        """
        session_dir = path.parent.absolute()
        data = json.loads(path.read_text(encoding="utf-8"))  # pyright: ignore[reportAny]
        if not isinstance(data, dict):
            raise TypeError(_ERR_BAD_JSON_ROOT)
        for field_name in _PATH_FIELDS:
            value = data.get(field_name)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
            if isinstance(value, str) and value:
                data[field_name] = _make_absolute(value, session_dir)
        return cls.model_validate(data)

    # ── validation ───────────────────────────────────────────────────────

    def validate_paths(self) -> list[str]:
        """Return the list of non-``None`` file paths that do not exist on disk.

        Only file-path fields are checked (``zoom_path``, ``qualtrics_path``,
        ``overrides_path``).  ``output_dir`` is intentionally skipped — it may
        not exist yet and will be created on first use.
        """
        missing: list[str] = []
        for field_name in ("zoom_path", "qualtrics_path", "overrides_path"):
            value = getattr(self, field_name)  # pyright: ignore[reportAny]
            if isinstance(value, str) and value and not Path(value).exists():
                missing.append(value)
        return missing
