"""Commit static exports through one descriptor-owned output transaction."""

from __future__ import annotations

import secrets
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path

import marimo_studio._delivery.assets as _assets
from marimo_studio._filesystem.secure import (
    SecureDirectory,
    SecureFileError,
    secure_directory,
)
from marimo_studio._processes.provider_operation import raise_process_cleanup
from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio.errors import StaticExportError


@dataclass(frozen=True)
class OutputTarget:
    path: Path
    identity: tuple[tuple[object, ...], ...] | None
    filesystem: SecureDirectory


def directory_identity(
    filesystem: SecureDirectory,
    path: Path,
) -> tuple[tuple[object, ...], ...] | None:
    return filesystem.directory_tree_identity(path, max_entries=100_000)


def validate_output(output: Path, studio: StudioWorkspace) -> Path:
    expanded = output.expanduser()
    if expanded.is_symlink():
        raise StaticExportError(f"Output is a symlink: {expanded}")
    resolved = expanded.resolve()
    if resolved == Path(resolved.anchor) or resolved == Path.home().resolve():
        raise StaticExportError(
            f"Choose a dedicated static export directory: {resolved}"
        )
    protected = [
        studio.notebook,
        studio.view_root,
        studio.notebook.parent / "public",
        *(project.root for project in studio.views.values()),
        _assets.runtime_assets_path(),
    ]
    for source in protected:
        source = source.resolve()
        if (
            source == resolved
            or source.is_relative_to(resolved)
            or resolved.is_relative_to(source)
        ):
            raise StaticExportError(
                f"Output overlaps a static export source: {resolved}"
            )
    return resolved


def output_target(
    filesystem: SecureDirectory,
    output: Path,
    *,
    force: bool,
) -> OutputTarget:
    try:
        filesystem.ensure_attached()
        identity = directory_identity(filesystem, output)
    except SecureFileError as error:
        raise StaticExportError(f"Output must be a directory: {output}") from error
    if identity is not None and not force:
        raise StaticExportError(
            f"Output already exists: {output}. Pass --force to replace it."
        )
    return OutputTarget(output, identity, filesystem)


def publish_absent(
    filesystem: SecureDirectory,
    staged: Path,
    output: Path,
) -> None:
    try:
        filesystem.rename_if_absent(staged, output)
    except FileExistsError as error:
        raise StaticExportError(
            f"Output changed while the static export was prepared: {output}. "
            "Run the export again."
        ) from error


def temporary_directory(filesystem: SecureDirectory, prefix: str) -> Path:
    for _attempt in range(128):
        path = filesystem.root / f"{prefix}{secrets.token_hex(8)}"
        try:
            filesystem.create_directory(path)
        except FileExistsError:
            continue
        return path
    raise StaticExportError(
        f"Could not reserve a temporary static export directory in {filesystem.root}"
    )


def _recovery_path(filesystem: SecureDirectory, output: Path) -> Path:
    recovery = temporary_directory(filesystem, f".{output.name}-recovery-")
    filesystem.rmdir(recovery)
    return recovery


def _restore_previous(
    filesystem: SecureDirectory,
    recovery: Path,
    output: Path,
) -> None:
    try:
        publish_absent(filesystem, recovery, output)
    except (OSError, StaticExportError) as error:
        raise StaticExportError(
            f"Output changed while the static export was committed: {output}. "
            f"The previous output is preserved at {recovery}."
        ) from error


def commit_bundle(staged: Path, target: OutputTarget) -> None:
    output = target.path
    filesystem = target.filesystem
    try:
        filesystem.ensure_attached()
    except OSError as error:
        raise_process_cleanup(error)
        raise StaticExportError(
            "Output parent changed while the static export was prepared: "
            f"{output.parent}. Run the export again."
        ) from error
    if target.identity is None:
        try:
            publish_absent(filesystem, staged, output)
        except StaticExportError:
            raise
        except OSError as error:
            raise StaticExportError(
                f"Could not create static export directory {output}: {error}"
            ) from error
        return

    recovery = _recovery_path(filesystem, output)
    try:
        if directory_identity(filesystem, output) != target.identity:
            raise StaticExportError(
                f"Output changed while the static export was prepared: {output}. "
                "Run the export again."
            )
        filesystem.replace(output, recovery)
        try:
            previous_identity = directory_identity(filesystem, recovery)
        except OSError as error:
            _restore_previous(filesystem, recovery, output)
            raise StaticExportError(
                f"Could not verify previous static export directory {output}: {error}"
            ) from error
        if previous_identity != target.identity:
            _restore_previous(filesystem, recovery, output)
            raise StaticExportError(
                f"Output changed while the static export was prepared: {output}. "
                "Run the export again."
            )
        try:
            publish_absent(filesystem, staged, output)
        except Exception:
            _restore_previous(filesystem, recovery, output)
            raise
    except StaticExportError:
        raise
    except OSError as error:
        raise StaticExportError(
            f"Could not replace static export directory {output}: {error}"
        ) from error
    with suppress(OSError):
        filesystem.remove_tree(recovery)


@contextmanager
def output_filesystem(output: Path) -> Iterator[SecureDirectory]:
    existing = output.parent
    while not existing.exists():
        existing = existing.parent
    try:
        if existing != output.parent:
            with secure_directory(existing) as ancestor:
                ancestor.ensure_directory(output.parent)
        with secure_directory(output.parent) as filesystem:
            filesystem.ensure_attached()
            yield filesystem
    except OSError as error:
        raise_process_cleanup(error)
        raise StaticExportError(
            f"Could not secure static export parent {output.parent}: {error}"
        ) from error
