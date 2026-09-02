"""Walk bounded regular-file trees without following symlinks."""

from __future__ import annotations

import os
from collections.abc import Callable, Collection, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from marimo_studio.errors import ConfigurationError


@dataclass(frozen=True)
class TreeEntry:
    path: Path
    kind: Literal["directory", "file", "symlink"]


def _walk_tree_entries(
    root: Path,
    *,
    label: str,
    excluded_roots: Collection[str],
    excluded_paths: Collection[Path],
    cancelled: Callable[[], bool] | None,
) -> Iterator[TreeEntry]:
    if root.is_symlink() or not root.is_dir():
        raise ConfigurationError(f"{label} root is unavailable: {root}")
    excluded = {path.absolute() for path in excluded_paths}

    def require_active() -> None:
        if cancelled is not None and cancelled():
            raise ConfigurationError(f"{label} scan was cancelled.")

    def visit(directory: Path, *, top_level: bool) -> Iterator[TreeEntry]:
        require_active()
        try:
            entries = os.scandir(directory)
        except OSError as error:
            raise ConfigurationError(
                f"Could not inspect {label}: {directory}"
            ) from error
        with entries:
            for entry in entries:
                require_active()
                path = Path(entry.path)
                absolute = path.absolute()
                if any(
                    absolute == candidate or candidate in absolute.parents
                    for candidate in excluded
                ):
                    continue
                if entry.is_symlink():
                    yield TreeEntry(path, "symlink")
                    continue
                if entry.is_dir(follow_symlinks=False):
                    if top_level and entry.name in excluded_roots:
                        continue
                    yield TreeEntry(path, "directory")
                    yield from visit(path, top_level=False)
                    continue
                if not entry.is_file(follow_symlinks=False):
                    raise ConfigurationError(
                        f"{label} contains a non-regular entry: {path}"
                    )
                yield TreeEntry(path, "file")

    yield from visit(root, top_level=True)


def bounded_tree_entries(
    root: Path,
    *,
    max_entries: int,
    label: str,
    excluded_roots: Collection[str] = (),
    excluded_paths: Collection[Path] = (),
    seen: set[Path] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> tuple[TreeEntry, ...]:
    """Walk one tree and stop after the first over-limit entry."""
    known = seen if seen is not None else set()
    result: list[TreeEntry] = []
    for entry in _walk_tree_entries(
        root,
        label=label,
        excluded_roots=excluded_roots,
        excluded_paths=excluded_paths,
        cancelled=cancelled,
    ):
        absolute = entry.path.absolute()
        if absolute in known:
            continue
        known.add(absolute)
        if len(known) > max_entries:
            raise ConfigurationError(
                f"{label} contains more than {max_entries} entries. "
                "Remove files or split the project."
            )
        result.append(entry)
    return tuple(result)


def bounded_regular_files(
    root: Path,
    *,
    max_files: int,
    label: str,
    excluded_roots: Collection[str] = (),
    excluded_paths: Collection[Path] = (),
    seen: set[Path] | None = None,
    seen_entries: set[Path] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> tuple[Path, ...]:
    """Walk regular files and stop after the first over-limit entry."""
    files: list[Path] = []
    known = seen if seen is not None else set()
    entries = bounded_tree_entries(
        root,
        max_entries=max_files,
        label=label,
        excluded_roots=excluded_roots,
        excluded_paths=excluded_paths,
        seen=seen_entries,
        cancelled=cancelled,
    )
    for entry in entries:
        if entry.kind == "symlink":
            raise ConfigurationError(f"{label} contains a symlink: {entry.path}")
        key = entry.path.absolute()
        if entry.kind != "file" or key in known:
            continue
        known.add(key)
        files.append(entry.path)
        if len(known) > max_files:
            raise ConfigurationError(
                f"{label} contains more than {max_files} files. "
                "Remove files or split the project."
            )
    return tuple(files)
