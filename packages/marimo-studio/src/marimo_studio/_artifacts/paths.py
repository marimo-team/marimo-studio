"""Normalize artifact paths and reject filesystem boundary escapes."""

from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import BinaryIO, cast

from marimo_studio._artifacts.limits import (
    ARTIFACT_OUTPUT_BUDGET,
    FileBudgetTracker,
)
from marimo_studio._artifacts.records import ArtifactFile
from marimo_studio._filesystem.secure import open_contained_file, secure_directory
from marimo_studio._filesystem.tree import bounded_regular_files
from marimo_studio.errors import ConfigurationError
from marimo_studio.view_providers import ViewProject
from marimo_studio.view_providers._validation import validate_relative_path


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
    root = root.absolute()
    path = path.absolute()
    try:
        relative = path.relative_to(root)
    except ValueError as error:
        raise ConfigurationError(
            f"{label} is outside its owning view project: {path}"
        ) from error

    current = root
    candidates = (
        root,
        *(
            root / PurePosixPath(*relative.parts[:index])
            for index in range(1, len(relative.parts) + 1)
        ),
    )
    for index, candidate in enumerate(candidates):
        current = candidate
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(mode):
            raise ConfigurationError(f"{label} contains a symlink: {current}")
        final = index == len(candidates) - 1
        if not final and not stat.S_ISDIR(mode):
            raise ConfigurationError(f"{label} has a non-directory ancestor: {current}")
        if final_kind == "directory" and final and not stat.S_ISDIR(mode):
            raise ConfigurationError(f"{label} must be a directory: {current}")
        if final_kind == "file" and final and not stat.S_ISREG(mode):
            raise ConfigurationError(f"{label} must be a regular file: {current}")


def ensure_secure_directory(root: Path, path: Path, label: str) -> None:
    assert_secure_path(root, path, label)
    try:
        with secure_directory(root) as filesystem:
            filesystem.ensure_directory(path)
    except OSError as error:
        raise ConfigurationError(f"Could not create {label}: {path}") from error
    assert_secure_path(root, path, label, final_kind="directory")


def open_secure_file(root: Path, path: Path, label: str) -> BinaryIO:
    """Open one contained regular file through a non-following descriptor."""
    try:
        descriptor = open_contained_file(root, path)
    except OSError as error:
        raise ConfigurationError(f"Could not open {label}: {path}") from error
    try:
        return os.fdopen(descriptor, "rb")
    except Exception:
        os.close(descriptor)
        raise


@contextmanager
def verified_secure_file(
    root: Path,
    path: Path,
    label: str,
    *,
    require_single_link: bool = False,
) -> Iterator[tuple[BinaryIO, os.stat_result]]:
    """Keep one contained file descriptor stable for a bounded operation."""
    stream = open_secure_file(root, path, label)
    try:
        before = os.fstat(stream.fileno())
        if require_single_link and before.st_nlink != 1:
            raise ConfigurationError(
                f"{label} must use one revision-owned inode: {path}"
            )
        yield stream, before
        after = os.fstat(stream.fileno())
        if (
            before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
            or before.st_ctime_ns != after.st_ctime_ns
            or (require_single_link and after.st_nlink != 1)
        ):
            raise ConfigurationError(f"{label} changed while it was read: {path}")
    except OSError as error:
        raise ConfigurationError(f"Could not read {label}: {path}") from error
    finally:
        stream.close()


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
    with verified_secure_file(root, path, label) as (stream, state):
        _require_file_size(path, label, state.st_size, max_bytes)
        payload = stream.read(state.st_size)
        if len(payload) != state.st_size or stream.read(1):
            raise ConfigurationError(f"{label} changed while it was read: {path}")
    return payload


def artifact_paths(root: Path) -> tuple[PurePosixPath, ...]:
    """Return the complete normalized path inventory for a regular file tree."""
    if root.is_symlink() or not root.is_dir():
        raise ConfigurationError(f"Artifact files root is unavailable: {root}")
    paths: list[PurePosixPath] = []
    budget = FileBudgetTracker(ARTIFACT_OUTPUT_BUDGET, "Artifact output")
    casefolded: dict[tuple[str, ...], PurePosixPath] = {}
    for path in bounded_regular_files(
        root,
        max_files=ARTIFACT_OUTPUT_BUDGET.max_files,
        label="Artifact files",
    ):
        relative = normalized_artifact_path(
            path.relative_to(root).as_posix(),
            "Artifact file path",
        )
        key = tuple(part.casefold() for part in relative.parts)
        conflicting = casefolded.get(key)
        if conflicting is not None:
            raise ConfigurationError(
                f"Artifact paths differ only by case: {conflicting} and {relative}"
            )
        casefolded[key] = relative
        budget.add(relative.as_posix(), 0)
        paths.append(relative)
    if not paths:
        raise ConfigurationError("Artifact contains no browser files")
    paths.sort(key=lambda path: path.as_posix())
    return tuple(paths)


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
