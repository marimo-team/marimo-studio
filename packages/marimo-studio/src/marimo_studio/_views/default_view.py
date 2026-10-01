"""Select the view a notebook serves at its main route."""

from __future__ import annotations

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
from marimo_studio._workspace.ownership import PresentViewOwner, require_owned_view
from marimo_studio._workspace.transactions import workspace_transaction
from marimo_studio.errors import ViewNotFoundError


def set_default_view(
    definition: StudioDefinition,
    name: str,
    *,
    owner: PresentViewOwner | None = None,
) -> StudioWorkspace:
    """Make one present view the default and return the updated workspace.

    Without an owner the selection works from the view projects on disk, so it
    also repairs a configuration whose default names a missing view.
    """
    with workspace_catalog_lock(definition.view_root):
        snapshot = snapshot_workspace_config(
            definition,
            reload_studio=load_studio_definition,
        )
        current = snapshot.studio
        if owner is None:
            views = tuple(discover_views(current.view_root))
            if name not in views:
                raise ViewNotFoundError(name, available=views)
        else:
            require_owned_view(materialize_studio_workspace(current), name, owner)
        with workspace_transaction(
            "Default view selection",
            current.root,
            default_view_writes(current, snapshot.source, name),
            expected=snapshot.expected_identities,
        ):
            return load_studio(current.config_path)
