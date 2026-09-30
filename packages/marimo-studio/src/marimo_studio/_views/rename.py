"""Move one view project to a new name and keep the catalog consistent.

A rename is one catalog transaction. The configuration default, the old name's
owner tombstone, and the new name's owner commit together, then the project
directory moves with an atomic no-replace rename. A failure before the
transaction ends moves the directory back and restores every file.
"""

from __future__ import annotations

from pathlib import Path

from marimo_studio._artifacts.retention import artifact_exclusion_guard
from marimo_studio._filesystem._secure_types import ConditionalWriteError
from marimo_studio._filesystem.io import reject_mutable_symlinks
from marimo_studio._filesystem.secure import SecureDirectory, secure_directory
from marimo_studio._views.publication_hold import read_publication_hold
from marimo_studio._workspace.config import (
    default_view_writes,
    load_studio,
    validate_view_name,
)
from marimo_studio._workspace.config_snapshot import snapshot_workspace_config
from marimo_studio._workspace.generation import view_generation
from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio._workspace.mutation_lock import (
    view_mutation_lock,
    view_retirement_lock,
)
from marimo_studio._workspace.transactions import write_file_transaction
from marimo_studio._workspace.view_owners import view_owner_transition
from marimo_studio.errors import (
    ConfigurationError,
    ViewExistsError,
    ViewGenerationConflictError,
    ViewNotFoundError,
    WorkspaceGenerationConflictError,
    WorkspaceMutationError,
)


def rename_view(
    studio: StudioWorkspace,
    name: str,
    new_name: str,
    *,
    expected_catalog_generation: str | None = None,
    expected_generation: str | None = None,
) -> StudioWorkspace:
    """Rename one view project and return the updated workspace."""
    validate_view_name(new_name)
    with (
        view_retirement_lock(studio.view_root, name),
        view_mutation_lock(studio.view_root, new_name),
    ):
        return _rename_view_locked(
            studio,
            name,
            new_name,
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


def _rename_view_locked(
    studio: StudioWorkspace,
    name: str,
    new_name: str,
    *,
    expected_catalog_generation: str,
    expected_generation: str | None,
) -> StudioWorkspace:
    snapshot = snapshot_workspace_config(studio, reload_studio=load_studio)
    current = snapshot.studio
    if current.catalog_generation != expected_catalog_generation:
        raise WorkspaceGenerationConflictError()
    if name not in current.views:
        raise ViewNotFoundError(name, available=tuple(current.views))
    project = current.views[name]
    live_generation = view_generation(project)
    if live_generation != expected_generation:
        raise ViewGenerationConflictError(name, live_generation)
    if new_name == name:
        return current
    source = current.view_root / name
    target = current.view_root / new_name
    if new_name in current.views or target.exists() or target.is_symlink():
        raise ViewExistsError(
            new_name,
            missing_manifest=not (target / "view.toml").is_file(),
        )
    hold = read_publication_hold(source)
    if hold is not None and hold.status == "active":
        raise ConfigurationError(
            f"Publication of view {name!r} is held by {hold.owner!r} until "
            f"{hold.expiry}. Release that hold, then rename the view."
        )
    reject_mutable_symlinks(
        current.root,
        {current.config_path, current.view_root, source},
    )
    old_owner, old_owner_source, old_owner_identity = view_owner_transition(
        current.view_root,
        name,
        present=False,
    )
    new_owner, new_owner_source, new_owner_identity = view_owner_transition(
        current.view_root,
        new_name,
        present=True,
    )
    writes = {old_owner: old_owner_source, new_owner: new_owner_source}
    if current.default_view == name:
        writes.update(default_view_writes(current, snapshot.source, new_name))
    expected = {
        **snapshot.expected_identities,
        old_owner: old_owner_identity,
        new_owner: new_owner_identity,
    }
    with (
        artifact_exclusion_guard(project),
        secure_directory(current.root) as filesystem,
    ):
        source_identity = filesystem.directory_identity(source)
        moved = False
        try:
            with write_file_transaction(current.root, writes, expected=expected):
                try:
                    filesystem.rename_if_absent(source, target)
                except FileExistsError as error:
                    raise ViewExistsError(new_name) from error
                moved = True
                filesystem.sync_parent(target)
                if filesystem.directory_identity(target) != source_identity:
                    raise ConfigurationError(
                        f"View {name!r} changed before its rename committed. "
                        "Run the operation again."
                    )
                updated = load_studio(current.config_path)
        except BaseException as error:
            # The transaction restored every file. Return the project to the
            # name those files describe.
            if moved:
                _restore_project(filesystem, target, source)
            if isinstance(error, ConditionalWriteError):
                raise WorkspaceMutationError(
                    "View rename",
                    recovery=error.recovery,
                    write_committed=error.committed is not None,
                ) from error
            raise
    return updated


def _restore_project(filesystem: SecureDirectory, target: Path, source: Path) -> None:
    try:
        filesystem.rename_if_absent(target, source)
        filesystem.sync_parent(source)
    except OSError as error:
        raise WorkspaceMutationError(
            "View rename",
            recovery=target,
            write_committed=False,
        ) from error
