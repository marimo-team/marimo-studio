"""Remove named views and keep the configured default valid."""

from __future__ import annotations

import secrets
from contextlib import suppress
from pathlib import Path

import tomlkit

from marimo_studio._artifacts.retention import artifact_deletion_guard
from marimo_studio._filesystem._secure_names import temporary_sibling_name
from marimo_studio._filesystem._secure_types import ConditionalWriteError
from marimo_studio._filesystem.io import (
    atomic_write_bytes,
    read_bytes,
    reject_mutable_symlinks,
)
from marimo_studio._filesystem.secure import (
    FileIdentity,
    SecureDirectory,
    secure_directory,
)
from marimo_studio._workspace.config import (
    editable_studio_config,
    load_studio,
)
from marimo_studio._workspace.config_snapshot import snapshot_workspace_config
from marimo_studio._workspace.generation import view_generation
from marimo_studio._workspace.metadata import updated_notebook_default_source
from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio._workspace.mutation_lock import view_removal_lock
from marimo_studio._workspace.transactions import write_file_transaction
from marimo_studio._workspace.view_owners import view_owner_transition
from marimo_studio.errors import (
    ConfigurationError,
    LastViewError,
    ViewDeletionError,
    ViewGenerationConflictError,
    ViewNotFoundError,
    WorkspaceGenerationConflictError,
    WorkspaceMutationError,
)

_TOMBSTONE_CANDIDATE = ".tombstone"
_TOMBSTONE_MARKER = ".marimo-studio-tombstone"
_VIEW_DELETION_MAX_ENTRIES = 100_000


def _require_directory_owner(
    filesystem: SecureDirectory,
    path: Path,
    expected: FileIdentity,
) -> None:
    current = filesystem.directory_identity(path)
    if (
        current.device != expected.device
        or current.inode != expected.inode
        or current.mode != expected.mode
    ):
        raise ConfigurationError(
            f"View deletion staging owner changed before commit: {path}"
        )


def validate_view_deletion_owner(
    studio: StudioWorkspace,
    name: str,
    *,
    expected_catalog_generation: str,
    expected_generation: str,
) -> StudioWorkspace:
    """Return the current workspace when deletion still owns both generations."""
    current = load_studio(studio.config_path)
    generation = current.view_generations.get(name)
    if current.catalog_generation != expected_catalog_generation:
        raise WorkspaceGenerationConflictError()
    if generation != expected_generation:
        raise ViewGenerationConflictError(name, generation)
    return current


def _deletion_writes(
    studio: StudioWorkspace,
    next_default: str,
    source: str,
) -> dict[Path, str]:
    if studio.uses_notebook_config:
        updated = updated_notebook_default_source(
            studio.notebook,
            source,
            default_view=next_default,
        )
        return {studio.notebook: updated} if updated != source else {}

    document = tomlkit.parse(source)
    editable_studio_config(document)["default"] = next_default
    updated = tomlkit.dumps(document)
    return {studio.config_path: updated} if updated != source else {}


def _remove_owned_tombstone(
    filesystem: SecureDirectory,
    target: Path,
    expected: FileIdentity,
    token: str,
) -> bool:
    if not filesystem.entry_exists(target):
        return True
    try:
        marker = read_bytes(target / _TOMBSTONE_MARKER, root=target).decode("ascii")
        current = filesystem.directory_identity(target)
    except (OSError, UnicodeError):
        return False
    if marker != token or current != expected:
        return False
    try:
        quarantine = filesystem.quarantine_directory_if_identity(target, expected)
    except OSError:
        return False
    try:
        filesystem.remove_tree(quarantine)
        filesystem.sync_parent(target)
    except OSError:
        return False
    return True


def _remove_empty_staging_root(
    filesystem: SecureDirectory,
    staging_root: Path,
) -> None:
    identity = filesystem.directory_identity(staging_root)
    quarantine = filesystem.quarantine_directory_if_identity(staging_root, identity)
    filesystem.rmdir(quarantine)
    filesystem.sync_parent(staging_root)


def _restore_staged_view(
    filesystem: SecureDirectory,
    staged: Path,
    target: Path,
    candidate: Path,
    staging_root: Path,
    tombstone_identity: FileIdentity | None,
    tombstone_token: str,
) -> Path | None:
    if not filesystem.entry_exists(staged):
        if filesystem.entry_exists(candidate):
            filesystem.remove_tree(candidate)
        with suppress(OSError):
            _remove_empty_staging_root(filesystem, staging_root)
        return None
    if tombstone_identity is not None and not _remove_owned_tombstone(
        filesystem,
        target,
        tombstone_identity,
        tombstone_token,
    ):
        return staged
    try:
        filesystem.rename_if_absent(staged, target)
    except OSError:
        return staged
    filesystem.sync_parent(staged)
    filesystem.sync_parent(target)
    if filesystem.entry_exists(candidate):
        with suppress(OSError):
            filesystem.remove_tree(candidate)
            filesystem.sync_parent(candidate)
    with suppress(OSError):
        _remove_empty_staging_root(filesystem, staging_root)
    return None


def _delete_view_locked(
    studio: StudioWorkspace,
    name: str,
    *,
    expected_catalog_generation: str,
    expected_generation: str | None,
) -> StudioWorkspace:
    snapshot = snapshot_workspace_config(
        studio,
        reload_studio=load_studio,
    )
    current = snapshot.studio
    current_generation = current.view_generations.get(name)
    if current.catalog_generation != expected_catalog_generation:
        raise WorkspaceGenerationConflictError()
    if current_generation != expected_generation:
        raise ViewGenerationConflictError(name, current_generation)
    if name not in current.views:
        raise ViewNotFoundError(name, available=tuple(current.views))
    if len(current.views) == 1:
        raise LastViewError()

    target = current.view_root / name
    live_generation = view_generation(current.views[name])
    if live_generation != expected_generation:
        raise ViewGenerationConflictError(name, live_generation)
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
    writes = _deletion_writes(current, next_default, snapshot.source)
    owner_path, owner_source, owner_identity = view_owner_transition(
        current.view_root,
        name,
        present=False,
    )
    writes[owner_path] = owner_source
    transaction_identities = {
        **snapshot.expected_identities,
        owner_path: owner_identity,
    }
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
        target_identity = filesystem.directory_identity(target)
        staging_root = current.view_root.parent / temporary_sibling_name("delete")
        staging_identity = filesystem.create_directory(staging_root)
        filesystem.sync_parent(staging_root)
        staged = staging_root / name
        candidate = staging_root / _TOMBSTONE_CANDIDATE
        tombstone_token = secrets.token_hex(16)
        tombstone_identity: FileIdentity | None = None
        updated: StudioWorkspace | None = None
        try:
            filesystem.create_directory(candidate)
            atomic_write_bytes(
                candidate / _TOMBSTONE_MARKER,
                tombstone_token.encode("ascii"),
                filesystem=filesystem,
            )
            filesystem.sync_parent(candidate / _TOMBSTONE_MARKER)
            tombstone_identity = filesystem.directory_identity(candidate)
            filesystem.sync_parent(candidate)
            _require_directory_owner(filesystem, staging_root, staging_identity)
            filesystem.replace(target, staged)
            filesystem.sync_parent(target)
            filesystem.sync_parent(staged)
            if filesystem.directory_identity(staged) != target_identity:
                raise ConfigurationError(
                    f"View {name!r} changed before deletion committed"
                )
            try:
                filesystem.rename_if_absent(candidate, target)
            except FileExistsError as error:
                raise ViewDeletionError(recovery=staged) from error
            if filesystem.directory_identity(target) != tombstone_identity:
                raise ViewDeletionError(recovery=staged)
            filesystem.sync_parent(candidate)
            filesystem.sync_parent(target)
            if (
                filesystem.directory_tree_identity(
                    staged,
                    max_entries=_VIEW_DELETION_MAX_ENTRIES,
                )
                != expected
            ):
                raise ConfigurationError(
                    f"View {name!r} changed before deletion committed"
                )
            with write_file_transaction(
                current.root,
                writes,
                expected=transaction_identities,
                expected_directories={target: tombstone_identity},
            ):
                updated = load_studio(current.config_path)
                if (
                    filesystem.directory_tree_identity(
                        staged,
                        max_entries=_VIEW_DELETION_MAX_ENTRIES,
                    )
                    != expected
                ):
                    raise ConfigurationError(
                        f"View {name!r} changed before deletion committed"
                    )
        except BaseException as error:
            recovery = _restore_staged_view(
                filesystem,
                staged,
                target,
                candidate,
                staging_root,
                tombstone_identity,
                tombstone_token,
            )
            if recovery is not None:
                raise ViewDeletionError(recovery=recovery) from error
            if isinstance(error, ConditionalWriteError):
                raise WorkspaceMutationError(
                    "View deletion",
                    recovery=error.recovery,
                    write_committed=error.committed is not None,
                ) from error
            if isinstance(error, OSError):
                raise ViewDeletionError() from error
            raise
        if updated is None:
            raise RuntimeError("View deletion did not produce an updated workspace")
        try:
            assert tombstone_identity is not None
            if not _remove_owned_tombstone(
                filesystem,
                target,
                tombstone_identity,
                tombstone_token,
            ):
                raise ViewDeletionError(
                    cleanup=staging_root,
                    committed_workspace=updated,
                )
            if (
                filesystem.directory_tree_identity(
                    staged,
                    max_entries=_VIEW_DELETION_MAX_ENTRIES,
                )
                != expected
            ):
                raise ViewDeletionError(
                    cleanup=staging_root,
                    committed_workspace=updated,
                )
            quarantine = filesystem.quarantine_directory_if_identity(
                staged,
                target_identity,
            )
            if (
                filesystem.directory_tree_identity(
                    quarantine,
                    max_entries=_VIEW_DELETION_MAX_ENTRIES,
                )
                != expected
            ):
                raise ViewDeletionError(
                    cleanup=staging_root,
                    committed_workspace=updated,
                )
            filesystem.remove_tree(quarantine)
            filesystem.sync_parent(staged)
            _remove_empty_staging_root(filesystem, staging_root)
        except ViewDeletionError:
            raise
        except OSError as error:
            raise ViewDeletionError(
                cleanup=staging_root,
                committed_workspace=updated,
            ) from error
    return updated


def delete_view(
    studio: StudioWorkspace,
    name: str,
    *,
    expected_catalog_generation: str | None = None,
    expected_generation: str | None = None,
) -> StudioWorkspace:
    """Delete one view directory and return the updated workspace."""
    with view_removal_lock(studio.view_root, name):
        return _delete_view_locked(
            studio,
            name,
            expected_catalog_generation=(
                studio.catalog_generation
                if expected_catalog_generation is None
                else expected_catalog_generation
            ),
            expected_generation=(
                studio.view_generations.get(name)
                if expected_generation is None
                else expected_generation
            ),
        )
