"""Move one view project to a new name and keep the catalog consistent.

A rename is one catalog transaction. The old name's owner becomes a tombstone,
the new name gets a fresh owner, a default view stays the default, and the
project directory moves with an atomic no-replace rename inside the
transaction. A failure restores every file and moves the directory back.
"""

from __future__ import annotations

import errno
from pathlib import Path

from marimo_studio._artifacts.retention import artifact_exclusion_guard
from marimo_studio._filesystem.files import FileTree
from marimo_studio._notebook.locking import notebook_write_lock
from marimo_studio._views.publication_hold import require_unheld
from marimo_studio._workspace.config import load_studio, validate_view_name
from marimo_studio._workspace.config_snapshot import snapshot_workspace_config
from marimo_studio._workspace.generation import directory_generation
from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio._workspace.mutation_lock import (
    view_mutation_lock,
    view_retirement_lock,
)
from marimo_studio._workspace.ownership import PresentViewOwner, require_owned_view
from marimo_studio._workspace.transactions import workspace_transaction
from marimo_studio.errors import (
    ConfigurationError,
    ViewExistsError,
    ViewNotFoundError,
    ViewRenameError,
    WorkspaceMutationError,
)


def require_rename_target(studio: StudioWorkspace, name: str, new_name: str) -> None:
    """Reject a rename whose new name is taken or whose publication is held."""
    target = studio.view_root / new_name
    if new_name in studio.views or target.exists() or target.is_symlink():
        raise ViewExistsError(
            new_name,
            missing_manifest=not (target / "view.toml").is_file(),
        )
    require_unheld(studio.view_root / name, "Release that hold, then rename the view.")


def rename_view(
    studio: StudioWorkspace,
    name: str,
    new_name: str,
    *,
    owner: PresentViewOwner | None = None,
) -> StudioWorkspace:
    """Rename one view project and return the updated workspace."""
    validate_view_name(new_name)
    with (
        view_retirement_lock(studio.view_root, name),
        view_mutation_lock(studio.view_root, new_name),
    ):
        snapshot = snapshot_workspace_config(studio, reload_studio=load_studio)
        current = snapshot.studio
        project = require_owned_view(current, name, owner)
        require_rename_target(current, name, new_name)
        source = current.view_root / name
        target = current.view_root / new_name
        tree = FileTree(current.root)
        tree.stat(source)
        writes, expected = snapshot.catalog_writes(
            [new_name if view == name else view for view in current.views],
            new_name if current.default_view == name else current.default_view,
        )
        with artifact_exclusion_guard(project):
            moved = False
            try:
                with (
                    notebook_write_lock(current.notebook, writes),
                    workspace_transaction(
                        "View rename",
                        current.root,
                        writes,
                        expected=expected,
                    ),
                ):
                    try:
                        source_generation = directory_generation(source)
                        tree.publish(source, target)
                        moved = True
                    except FileExistsError as error:
                        raise ViewExistsError(new_name) from error
                    except FileNotFoundError as error:
                        raise ViewNotFoundError(
                            name,
                            available=tuple(current.views),
                        ) from error
                    except OSError as error:
                        raise _rename_error(name, new_name, error) from error
                    if directory_generation(target) != source_generation:
                        raise ConfigurationError(
                            f"View {name!r} changed before its rename committed. "
                            "Run the operation again."
                        )
                    return load_studio(current.config_path)
            except BaseException as error:
                # The transaction restored every file, including when its
                # post-commit checks fail. Return the project to the name those
                # files describe.
                if moved and not _moved_back(tree, target, source):
                    raise WorkspaceMutationError(
                        "View rename",
                        recovery=target,
                        write_committed=False,
                    ) from error
                raise


def _rename_error(name: str, new_name: str, error: OSError) -> ViewRenameError:
    # Windows reports an open handle inside the folder as access denied or as
    # a sharing violation.
    busy = error.errno == errno.EBUSY or getattr(error, "winerror", None) in {5, 32}
    return ViewRenameError(name, new_name, error.strerror or str(error), busy=busy)


def _moved_back(tree: FileTree, target: Path, source: Path) -> bool:
    try:
        tree.publish(target, source)
    except OSError:
        return False
    return True
