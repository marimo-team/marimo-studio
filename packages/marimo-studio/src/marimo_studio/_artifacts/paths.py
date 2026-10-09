"""Normalize artifact paths and reject filesystem boundary escapes."""

from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import BinaryIO, cast

from marimo_studio._artifacts.limits import (
    ARTIFACT_OUTPUT_BUDGET,
    FileBudgetTracker,
)
from marimo_studio._artifacts.records import ArtifactFile
from marimo_studio._filesystem.errors import UnsafePathError
from marimo_studio._filesystem.files import FileTree
from marimo_studio._filesystem.paths import validate_relative_path
from marimo_studio.errors import ConfigurationError
from marimo_studio.view_providers import ViewProject


def _unsafe(label: str, error: UnsafePathError) -> ConfigurationError:
    return ConfigurationError(f"{label} is unsafe. {error}")


def artifact_root(project: ViewProject) -> Path:
    """Return Studio's private generated-state root for one view."""
    return project.root / ".artifacts"


def normalized_artifact_path(value: object, label: str) -> PurePosixPath:
    """Return one canonical project-relative POSIX path."""
    try:
        return validate_relative_path(
            cast(str | PurePosixPath, value),
            field=label,
        )
    except ValueError as error:
        raise ConfigurationError(str(error)) from error


def assert_secure_path(
    root: Path,
    path: Path,
    label: str,
    *,
    final_kind: str | None = None,
) -> None:
    """Reject paths outside ``root`` and every existing symlink component."""
    try:
        state = FileTree(root).stat(path)
    except UnsafePathError as error:
        raise _unsafe(label, error) from error
    if state is None:
        return
    if final_kind == "directory" and not stat.S_ISDIR(state.st_mode):
        raise ConfigurationError(f"{label} must be a directory: {path}")
    if final_kind == "file" and not stat.S_ISREG(state.st_mode):
        raise ConfigurationError(f"{label} must be a regular file: {path}")


def ensure_secure_directory(root: Path, path: Path, label: str) -> None:
    try:
        FileTree(root).ensure_directory(path)
    except UnsafePathError as error:
        raise _unsafe(label, error) from error
    except OSError as error:
        raise ConfigurationError(f"Could not create {label}: {path}") from error


@contextmanager
def verified_secure_file(
    root: Path,
    path: Path,
    label: str,
    *,
    require_single_link: bool = False,
) -> Iterator[tuple[BinaryIO, os.stat_result]]:
    """Keep one contained file descriptor stable for a bounded operation.

    ``require_single_link`` refuses a file that shares its inode with another
    name, so a revision never aliases a file that a writer can still reach.
    """
    try:
        with FileTree(root).reader(path) as (stream, state):
            if require_single_link and state.st_nlink != 1:
                raise ConfigurationError(
                    f"{label} must use one revision-owned inode: {path}"
                )
            yield stream, state
            # A link added while the file was read would let another name
            # change the revision later.
            if require_single_link and os.fstat(stream.fileno()).st_nlink != 1:
                raise ConfigurationError(
                    f"{label} must use one revision-owned inode: {path}"
                )
    except UnsafePathError as error:
        raise _unsafe(label, error) from error
    except ConfigurationError:
        raise
    except OSError as error:
        raise ConfigurationError(f"Could not read {label}: {path}") from error


def _require_file_size(path: Path, label: str, size: int, max_bytes: int) -> None:
    if size > max_bytes:
        raise ConfigurationError(
            f"{label} is {size} bytes. The limit is {max_bytes} bytes: {path}"
        )


def digest_secure_file(
    root: Path,
    path: Path,
    label: str,
    *,
    max_bytes: int,
) -> str:
    """Hash one stable regular file after checking its allocation bound."""
    digest = hashlib.sha256()
    with verified_secure_file(root, path, label) as (stream, state):
        _require_file_size(path, label, state.st_size, max_bytes)
        remaining = state.st_size
        while remaining:
            chunk = stream.read(min(1024 * 1024, remaining))
            if not chunk:
                raise ConfigurationError(f"{label} changed while it was read: {path}")
            digest.update(chunk)
            remaining -= len(chunk)
        if stream.read(1):
            raise ConfigurationError(f"{label} changed while it was read: {path}")
    return digest.hexdigest()


def read_secure_bytes(
    root: Path,
    path: Path,
    label: str,
    *,
    max_bytes: int = ARTIFACT_OUTPUT_BUDGET.max_file_bytes,
) -> bytes:
    """Read one contained regular file through a non-following descriptor."""
    try:
        return FileTree(root).read(path, max_bytes=max_bytes).content
    except UnsafePathError as error:
        raise _unsafe(label, error) from error
    except ConfigurationError:
        raise
    except OSError as error:
        raise ConfigurationError(f"Could not read {label}: {path}") from error


def validated_artifact_paths(paths: Iterable[str]) -> tuple[PurePosixPath, ...]:
    """Return canonical artifact paths in order after rejecting case collisions."""
    validated: list[PurePosixPath] = []
    casefolded: dict[tuple[str, ...], PurePosixPath] = {}
    for value in paths:
        relative = normalized_artifact_path(value, "Artifact file path")
        key = tuple(part.casefold() for part in relative.parts)
        conflicting = casefolded.get(key)
        if conflicting is not None:
            raise ConfigurationError(
                f"Artifact paths differ only by case: {conflicting} and {relative}"
            )
        casefolded[key] = relative
        validated.append(relative)
    if not validated:
        raise ConfigurationError("Artifact contains no browser files")
    validated.sort(key=lambda path: path.as_posix())
    return tuple(validated)


def artifact_paths(root: Path) -> tuple[PurePosixPath, ...]:
    """Return the complete normalized path inventory for a regular file tree."""
    if root.is_symlink() or not root.is_dir():
        raise ConfigurationError(f"Artifact files root is unavailable: {root}")
    tree = FileTree(root)
    try:
        files = tree.regular_files(root, max_entries=ARTIFACT_OUTPUT_BUDGET.max_files)
    except UnsafePathError as error:
        raise _unsafe("Artifact files", error) from error
    except ConfigurationError:
        raise
    except OSError as error:
        raise ConfigurationError(f"Could not inspect artifact files: {root}") from error
    relatives = [path.relative_to(tree.root).as_posix() for path, _size in files]
    budget = FileBudgetTracker(ARTIFACT_OUTPUT_BUDGET, "Artifact output")
    for relative in relatives:
        budget.add(relative, 0)
    return validated_artifact_paths(relatives)


def artifact_files(root: Path) -> tuple[ArtifactFile, ...]:
    """Return a complete, hashed inventory of one regular file tree."""
    paths = artifact_paths(root)
    files: list[ArtifactFile] = []
    budget = FileBudgetTracker(ARTIFACT_OUTPUT_BUDGET, "Artifact output")
    for relative in paths:
        path = root.joinpath(*relative.parts)
        digest = hashlib.sha256()
        with verified_secure_file(
            root,
            path,
            "Artifact file",
            require_single_link=True,
        ) as (stream, state):
            budget.add(relative.as_posix(), state.st_size)
            remaining = state.st_size
            while remaining:
                chunk = stream.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise ConfigurationError(
                        f"Artifact file changed while it was read: {path}"
                    )
                digest.update(chunk)
                remaining -= len(chunk)
            if stream.read(1):
                raise ConfigurationError(
                    f"Artifact file changed while it was read: {path}"
                )
        files.append(ArtifactFile(relative, digest.hexdigest(), state.st_size))
    return tuple(files)
