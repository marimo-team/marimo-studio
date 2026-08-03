"""Protect and atomically replace mutable workspace files."""

from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path

from marimo_studio.errors import ConfigurationError


def read_text(path: Path) -> str:
    """Read UTF-8 text without translating line endings."""
    with path.open("r", encoding="utf-8", newline="") as stream:
        return stream.read()


def reject_mutable_symlinks(root: Path, paths: set[Path]) -> None:
    """Reject symlinks between the workspace root and each mutable path."""
    root = root.absolute()
    for path in paths:
        candidate = path.absolute()
        try:
            relative = candidate.relative_to(root)
        except ValueError as error:
            raise ConfigurationError(
                f"Mutable workspace path is outside the workspace root: {candidate}"
            ) from error
        current = root
        for part in relative.parts:
            current /= part
            if current.is_symlink():
                raise ConfigurationError(
                    f"Mutable workspace path is a symlink: {current}"
                )


def atomic_write_text(path: Path, content: str) -> None:
    """Replace a text file through a temporary file in the same directory."""
    if path.is_symlink():
        raise ConfigurationError(f"Mutable workspace path is a symlink: {path}")
    mode = (
        stat.S_IMODE(path.stat(follow_symlinks=False).st_mode)
        if path.exists()
        else None
    )
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(
            descriptor,
            "w",
            encoding="utf-8",
            newline="",
        ) as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if mode is not None:
            temporary.chmod(mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
