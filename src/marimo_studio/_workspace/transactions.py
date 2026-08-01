"""Apply related workspace text writes as one recoverable operation."""

from __future__ import annotations

from contextlib import suppress
from pathlib import Path

from marimo_studio._workspace.files import (
    atomic_write_text,
    read_text,
    reject_mutable_symlinks,
)
from marimo_studio.errors import ConfigurationError


def write_text_transaction(root: Path, writes: dict[Path, str]) -> None:
    """Write text files and restore their prior contents after a failure."""
    reject_mutable_symlinks(root, set(writes))
    snapshots = {path: read_text(path) if path.is_file() else None for path in writes}
    created_directories: set[Path] = set()
    for path in writes:
        current = path.parent
        while current != root and not current.exists():
            created_directories.add(current)
            parent = current.parent
            if parent == current:
                raise ConfigurationError(
                    f"Mutable view path is outside the notebook directory: {path}"
                )
            current = parent
    try:
        for path, content in writes.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(path, content)
    except Exception:
        for path, content in snapshots.items():
            if content is None:
                path.unlink(missing_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                atomic_write_text(path, content)
        for directory in sorted(
            created_directories,
            key=lambda path: len(path.parts),
            reverse=True,
        ):
            with suppress(OSError):
                directory.rmdir()
        raise
