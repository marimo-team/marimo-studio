"""Select the view a notebook serves at its main route."""

from __future__ import annotations

from marimo_studio._filesystem._secure_types import ConditionalWriteError
from marimo_studio._workspace.config import default_view_writes, load_studio
from marimo_studio._workspace.config_snapshot import snapshot_workspace_config
from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio._workspace.mutation_lock import workspace_catalog_lock
from marimo_studio._workspace.transactions import write_file_transaction
from marimo_studio.errors import (
    ViewGenerationConflictError,
    ViewNotFoundError,
    WorkspaceGenerationConflictError,
    WorkspaceMutationError,
)


def set_default_view(
    studio: StudioWorkspace,
    name: str,
    *,
    expected_catalog_generation: str | None = None,
    expected_generation: str | None = None,
) -> StudioWorkspace:
    """Make one present view the default and return the updated workspace."""
    catalog_generation = (
        studio.catalog_generation
        if expected_catalog_generation is None
        else expected_catalog_generation
    )
    with workspace_catalog_lock(studio.view_root):
        snapshot = snapshot_workspace_config(studio, reload_studio=load_studio)
        current = snapshot.studio
        if current.catalog_generation != catalog_generation:
            raise WorkspaceGenerationConflictError()
        if name not in current.views:
            raise ViewNotFoundError(name, available=tuple(current.views))
        generation = current.view_generations[name]
        if expected_generation is not None and generation != expected_generation:
            raise ViewGenerationConflictError(name, generation)
        writes = default_view_writes(current, snapshot.source, name)
        if not writes:
            return current
        try:
            with write_file_transaction(
                current.root,
                writes,
                expected=snapshot.expected_identities,
            ):
                pass
        except ConditionalWriteError as error:
            raise WorkspaceMutationError(
                "Default view selection",
                recovery=error.recovery,
                write_committed=error.committed is not None,
            ) from error
        return load_studio(current.config_path)
