"""Select the view a notebook serves at its main route."""

from __future__ import annotations

from marimo_studio._filesystem._secure_types import ConditionalWriteError
from marimo_studio._workspace.config import (
    default_view_writes,
    discover_views,
    load_studio,
    load_studio_definition,
    materialize_studio_workspace,
)
from marimo_studio._workspace.config_snapshot import snapshot_workspace_config
from marimo_studio._workspace.models import StudioDefinition, StudioWorkspace
from marimo_studio._workspace.mutation_lock import workspace_catalog_lock
from marimo_studio._workspace.transactions import write_file_transaction
from marimo_studio.errors import (
    ViewGenerationConflictError,
    ViewNotFoundError,
    WorkspaceGenerationConflictError,
    WorkspaceMutationError,
)


def set_default_view(
    definition: StudioDefinition,
    name: str,
    *,
    expected_catalog_generation: str | None = None,
    expected_generation: str | None = None,
) -> StudioWorkspace:
    """Make one present view the default and return the updated workspace.

    Without expected generations, the selection works from the discovered
    views. It can then repair a configuration whose default names a missing
    view, which an interrupted rename or removal can leave behind.
    """
    with workspace_catalog_lock(definition.view_root):
        snapshot = snapshot_workspace_config(
            definition,
            reload_studio=load_studio_definition,
        )
        current = snapshot.studio
        if expected_catalog_generation is None and expected_generation is None:
            views = tuple(discover_views(current.view_root))
        else:
            workspace = materialize_studio_workspace(current)
            if workspace.catalog_generation != expected_catalog_generation:
                raise WorkspaceGenerationConflictError()
            views = tuple(workspace.views)
            generation = workspace.view_generations.get(name)
            if name in views and generation != expected_generation:
                raise ViewGenerationConflictError(name, generation)
        if name not in views:
            raise ViewNotFoundError(name, available=views)
        try:
            with write_file_transaction(
                current.root,
                default_view_writes(current, snapshot.source, name),
                expected=snapshot.expected_identities,
            ):
                updated = load_studio(current.config_path)
        except ConditionalWriteError as error:
            raise WorkspaceMutationError(
                "Default view selection",
                recovery=error.recovery,
                write_committed=error.committed is not None,
            ) from error
        return updated
