"""Remove named views and keep the configured default valid."""

from __future__ import annotations

import secrets
from contextlib import suppress
from pathlib import Path

import tomlkit

from marimo_studio._artifacts.retention import artifact_deletion_guard
from marimo_studio._filesystem.io import (
    read_text,
    reject_mutable_symlinks,
)
from marimo_studio._filesystem.secure import SecureDirectory, secure_directory
from marimo_studio._workspace.config import (
    editable_studio_config,
    load_studio,
)
from marimo_studio._workspace.metadata import updated_notebook_default_source
from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio._workspace.mutation_lock import (
    view_build_lock,
    view_mutation_lock,
    workspace_catalog_lock,
)
from marimo_studio._workspace.transactions import write_file_transaction
from marimo_studio.errors import ConfigurationError, LastViewError, ViewNotFoundError
from marimo_studio.errors._internal import ViewDeletionError

_VIEW_DELETION_MAX_ENTRIES = 100_000


def _deletion_writes(
    studio: StudioWorkspace,
    next_default: str,
) -> dict[Path, str]:
    if studio.uses_notebook_config:
        source = read_text(studio.notebook)
        updated = updated_notebook_default_source(
            studio.notebook,
            source,
            default_view=next_default,
        )
        return {studio.notebook: updated} if updated != source else {}

    source = read_text(studio.config_path)
    document = tomlkit.parse(source)
    editable_studio_config(document)["default"] = next_default
    updated = tomlkit.dumps(document)
    return {studio.config_path: updated} if updated != source else {}


def _restore_staged_view(
    filesystem: SecureDirectory,
    staged: Path,
    target: Path,
    staging_root: Path,
) -> None:
    try:
        filesystem.directory_identity(staged)
    except FileNotFoundError:
        return
    try:
        filesystem.directory_identity(target)
    except FileNotFoundError:
        filesystem.replace(staged, target)
    with suppress(OSError):
        filesystem.rmdir(staging_root)


def _delete_view_locked(studio: StudioWorkspace, name: str) -> StudioWorkspace:
    current = load_studio(studio.config_path)
    if name not in current.views:
        raise ViewNotFoundError(name, available=tuple(current.views))
    if len(current.views) == 1:
        raise LastViewError()

    target = current.view_root / name
    reject_mutable_symlinks(
        current.root,
        {current.config_path, current.view_root.parent, target},
    )
    if not target.is_dir() or not (target / "view.toml").is_file():
        raise ViewNotFoundError(name, available=tuple(current.views))

    remaining = tuple(view for view in current.views if view != name)
    next_default = (
        remaining[0] if current.default_view == name else current.default_view
    )
    writes = _deletion_writes(current, next_default)
    with (
        artifact_deletion_guard(current.views[name]),
        secure_directory(current.root) as filesystem,
    ):
        expected = filesystem.directory_tree_identity(
            target,
            max_entries=_VIEW_DELETION_MAX_ENTRIES,
        )
        if expected is None:
            raise ViewNotFoundError(name, available=tuple(current.views))
        staging_root = current.view_root.parent / (
            f".{current.view_root.name}-{name}-{secrets.token_hex(16)}"
        )
        filesystem.create_directory(staging_root)
        staged = staging_root / name
        updated: StudioWorkspace | None = None
        try:
            filesystem.replace(target, staged)
            if (
                filesystem.directory_tree_identity(
                    staged,
                    max_entries=_VIEW_DELETION_MAX_ENTRIES,
                )
                != expected
            ):
                _restore_staged_view(filesystem, staged, target, staging_root)
                raise ConfigurationError(
                    f"View {name!r} changed before deletion committed"
                )
            try:
                with write_file_transaction(current.root, writes):
                    updated = load_studio(current.config_path)
            except BaseException:
                _restore_staged_view(filesystem, staged, target, staging_root)
                raise
        except BaseException:
            with suppress(OSError):
                filesystem.rmdir(staging_root)
            raise
        try:
            filesystem.remove_tree(staging_root)
        except OSError as error:
            raise ViewDeletionError(staging_root) from error
    if updated is None:
        raise RuntimeError("View deletion did not produce an updated workspace")
    return updated


def delete_view(studio: StudioWorkspace, name: str) -> StudioWorkspace:
    """Delete one view directory and return the updated workspace."""
    with (
        workspace_catalog_lock(studio.view_root),
        view_build_lock(studio.view_root, name),
        view_mutation_lock(studio.view_root, name),
    ):
        return _delete_view_locked(studio, name)
