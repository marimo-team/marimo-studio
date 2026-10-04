"""Remove named views and keep the configured default valid."""

from __future__ import annotations

import secrets
from contextlib import suppress
from pathlib import Path

from marimo_studio._artifacts.retention import artifact_exclusion_guard
from marimo_studio._filesystem.files import ABSENT, FileTree, Version
from marimo_studio._filesystem.names import temporary_name
from marimo_studio._notebook.locking import notebook_write_lock
from marimo_studio._workspace.config import load_studio
from marimo_studio._workspace.config_snapshot import snapshot_workspace_config
from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio._workspace.mutation_lock import view_retirement_lock
from marimo_studio._workspace.ownership import PresentViewOwner, require_owned_view
from marimo_studio._workspace.transactions import workspace_transaction
from marimo_studio.errors import (
    ConfigurationError,
    LastViewError,
    ViewDeletionError,
    ViewNotFoundError,
)

_TOMBSTONE_CANDIDATE = ".tombstone"
_TOMBSTONE_MARKER = ".marimo-studio-tombstone"
_VIEW_DELETION_MAX_ENTRIES = 100_000


def _remove_owned_tombstone(
    tree: FileTree,
    target: Path,
    expected: Version,
    token: str,
) -> bool:
    if not tree.exists(target):
        return True
    try:
        marker = tree.read(target / _TOMBSTONE_MARKER).content.decode("ascii")
    except (OSError, UnicodeError):
        return False
    if marker != token:
        return False
    try:
        tree.remove(target, expect=expected)
    except OSError:
        return False
    return True


def _restore_staged_view(
    tree: FileTree,
    staged: Path,
    target: Path,
    candidate: Path,
    staging_root: Path,
    tombstone: Version | None,
    tombstone_token: str,
) -> Path | None:
    if not tree.exists(staged):
        tree.remove(candidate)
        with suppress(OSError):
            tree.remove_empty_directory(staging_root)
        return None
    if tombstone is not None and not _remove_owned_tombstone(
        tree,
        target,
        tombstone,
        tombstone_token,
    ):
        return staged
    try:
        tree.publish(staged, target)
    except OSError:
        return staged
    with suppress(OSError):
        tree.remove(candidate)
        tree.remove_empty_directory(staging_root)
    return None


def require_removable(studio: StudioWorkspace, name: str) -> None:
    """Reject removing the only view of a notebook."""
    if len(studio.views) == 1:
        raise LastViewError()


def _delete_view_locked(
    studio: StudioWorkspace,
    name: str,
    owner: PresentViewOwner | None,
) -> StudioWorkspace:
    snapshot = snapshot_workspace_config(
        studio,
        reload_studio=load_studio,
    )
    current = snapshot.studio
    project = require_owned_view(current, name, owner)
    require_removable(current, name)
    target = current.view_root / name
    tree = FileTree(current.root)
    if not tree.is_directory(target) or not tree.is_file(target / "view.toml"):
        raise ViewNotFoundError(name, available=tuple(current.views))

    remaining = tuple(view for view in current.views if view != name)
    writes, transaction_identities = snapshot.catalog_writes(
        remaining,
        remaining[0] if current.default_view == name else current.default_view,
    )
    with artifact_exclusion_guard(project):
        expected = tree.tree_version(target, max_entries=_VIEW_DELETION_MAX_ENTRIES)
        target_version = tree.version(target)
        if expected is None or target_version is None:
            raise ViewNotFoundError(name, available=tuple(current.views))
        staging_root = current.view_root.parent / temporary_name("stage")
        tree.create_directory(staging_root)
        staged = staging_root / name
        candidate = staging_root / _TOMBSTONE_CANDIDATE
        tombstone_token = secrets.token_hex(16)
        tombstone: Version | None = None
        updated: StudioWorkspace | None = None
        try:
            # A tombstone holds the name while the catalog transaction runs,
            # so a restore never meets a directory created in the meantime.
            tree.create_directory(candidate)
            tree.write(
                candidate / _TOMBSTONE_MARKER,
                tombstone_token.encode("ascii"),
                expect=ABSENT,
            )
            tombstone = tree.version(candidate)
            tree.publish(target, staged)
            if tree.version(staged) != target_version:
                raise ConfigurationError(
                    f"View {name!r} changed before deletion committed"
                )
            try:
                tree.publish(candidate, target)
            except FileExistsError as error:
                raise ViewDeletionError(recovery=staged) from error
            if tombstone is None or tree.version(target) != tombstone:
                raise ViewDeletionError(recovery=staged)
            if (
                tree.tree_version(staged, max_entries=_VIEW_DELETION_MAX_ENTRIES)
                != expected
            ):
                raise ConfigurationError(
                    f"View {name!r} changed before deletion committed"
                )
            with (
                notebook_write_lock(current.notebook, writes),
                workspace_transaction(
                    "View deletion",
                    current.root,
                    writes,
                    expected={**transaction_identities, target: tombstone},
                ),
            ):
                updated = load_studio(current.config_path)
                if (
                    tree.tree_version(staged, max_entries=_VIEW_DELETION_MAX_ENTRIES)
                    != expected
                ):
                    raise ConfigurationError(
                        f"View {name!r} changed before deletion committed"
                    )
        except BaseException as error:
            recovery = _restore_staged_view(
                tree,
                staged,
                target,
                candidate,
                staging_root,
                tombstone,
                tombstone_token,
            )
            if recovery is not None:
                raise ViewDeletionError(recovery=recovery) from error
            if isinstance(error, OSError):
                raise ViewDeletionError() from error
            raise
        if updated is None or tombstone is None:
            raise RuntimeError("View deletion did not produce an updated workspace")
        try:
            if not _remove_owned_tombstone(tree, target, tombstone, tombstone_token):
                raise ViewDeletionError(
                    cleanup=staging_root,
                    committed_workspace=updated,
                )
            tree.remove(staged, expect=expected)
            tree.remove_empty_directory(staging_root)
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
    owner: PresentViewOwner | None = None,
) -> StudioWorkspace:
    """Delete one view directory and return the updated workspace."""
    with view_retirement_lock(studio.view_root, name):
        return _delete_view_locked(studio, name, owner)
