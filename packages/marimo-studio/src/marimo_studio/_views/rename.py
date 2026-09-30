"""Move one view project to a new name and keep the catalog consistent.

A rename is one catalog transaction. The configuration default, the old name's
owner tombstone, and the new name's owner commit together, then the project
directory moves with an atomic no-replace rename. A failure restores every file
and moves the directory back. When the directory cannot move back before the
files commit, the transaction keeps the files that describe the new name, so
the workspace stays consistent under that name.
"""

from __future__ import annotations

import errno
from contextlib import suppress
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
    PublicationHeldError,
    ViewExistsError,
    ViewGenerationConflictError,
    ViewNotFoundError,
    ViewRenameError,
    WorkspaceGenerationConflictError,
    WorkspaceMutationError,
)


def require_rename_target(studio: StudioWorkspace, name: str, new_name: str) -> None:
    """Reject a rename whose new name is taken or whose publication is held."""
    target = studio.view_root / new_name
    if new_name != name and (
        new_name in studio.views or target.exists() or target.is_symlink()
    ):
        raise ViewExistsError(
            new_name,
            missing_manifest=not (target / "view.toml").is_file(),
        )
    hold = read_publication_hold(studio.view_root / name)
    if hold is not None and hold.status == "active":
        raise PublicationHeldError(
            name,
            hold.owner,
            hold.expiry,
            "Release that hold, then rename the view.",
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
    require_rename_target(current, name, new_name)
    if new_name == name:
        return current
    source = current.view_root / name
    target = current.view_root / new_name
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
    writes = {
        old_owner: old_owner_source,
        new_owner: new_owner_source,
        **default_view_writes(
            current,
            snapshot.source,
            new_name if current.default_view == name else current.default_view,
        ),
    }
    expected = {
        **snapshot.expected_identities,
        old_owner: old_owner_identity,
        new_owner: new_owner_identity,
    }
    with (
        artifact_exclusion_guard(project),
        secure_directory(current.root) as filesystem,
    ):
        source_owner = filesystem.directory_owner(source)
        moved = False
        outcome: StudioWorkspace | Exception | None = None
        try:
            with write_file_transaction(current.root, writes, expected=expected):
                try:
                    filesystem.rename_if_absent(source, target)
                except FileExistsError as error:
                    raise ViewExistsError(new_name) from error
                except OSError as error:
                    raise _rename_error(name, new_name, error) from error
                moved = True
                try:
                    filesystem.sync_parent(target)
                    if filesystem.directory_owner(target) != source_owner:
                        raise ConfigurationError(
                            f"View {name!r} changed before its rename committed. "
                            "Run the operation again."
                        )
                    outcome = load_studio(current.config_path)
                except Exception as error:
                    if not _moved_back(filesystem, target, source):
                        # The project stays at the new name, so commit the
                        # files that describe it.
                        outcome = error
                    else:
                        moved = False
                        if isinstance(error, OSError):
                            raise _rename_error(name, new_name, error) from error
                        raise
        except BaseException as error:
            # The transaction restored every file, including after its own
            # post-commit checks fail. Return the project to the name those
            # files describe.
            if moved and not _moved_back(filesystem, target, source):
                raise WorkspaceMutationError(
                    "View rename",
                    recovery=target,
                    write_committed=False,
                ) from error
            if isinstance(error, ConditionalWriteError):
                raise WorkspaceMutationError(
                    "View rename",
                    recovery=error.recovery,
                    write_committed=error.committed is not None,
                ) from error
            raise
    if not isinstance(outcome, StudioWorkspace):
        raise WorkspaceMutationError(
            "View rename",
            recovery=target,
            write_committed=True,
        ) from outcome
    return outcome


def _rename_error(name: str, new_name: str, error: OSError) -> ViewRenameError:
    # Windows reports an open handle inside the folder as access denied or as
    # a sharing violation.
    busy = error.errno == errno.EBUSY or getattr(error, "winerror", None) in {5, 32}
    return ViewRenameError(name, new_name, error.strerror or str(error), busy=busy)


def _moved_back(filesystem: SecureDirectory, target: Path, source: Path) -> bool:
    try:
        filesystem.rename_if_absent(target, source)
    except OSError:
        return False
    # The project is back at the name the restored files describe. A failed
    # directory sync leaves only the durability of that rename open.
    with suppress(OSError):
        filesystem.sync_parent(source)
    return True
