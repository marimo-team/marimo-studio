"""Inspect Studio workspace state before authoring a view."""

from __future__ import annotations

from pathlib import Path

from marimo_studio._artifacts.repository import read_artifact_state
from marimo_studio._views.inspection import inspect_view_project_sync
from marimo_studio._views.records import StudioOverview, ViewOverview
from marimo_studio._workspace.config import (
    canonical_view_root,
    discover_studio_definition,
    discover_views,
)
from marimo_studio._workspace.generation import (
    directory_generation,
    view_generation,
    workspace_catalog_generation,
)
from marimo_studio._workspace.view_owners import reconcile_view_owners
from marimo_studio.errors import ConfigurationError
from marimo_studio.view_providers._host.requirements import (
    resolve_launch_requirements,
)


def overview(notebook: str | Path) -> StudioOverview:
    """Return Studio configuration and view state for a saved notebook."""
    notebook_path = Path(notebook).expanduser().resolve()
    if not notebook_path.is_file():
        raise ConfigurationError(f"Notebook does not exist: {notebook_path}")
    if notebook_path.suffix != ".py":
        raise ConfigurationError(f"Expected a Python Marimo notebook: {notebook_path}")

    definition = discover_studio_definition(notebook_path)
    if definition is None:
        return StudioOverview(
            notebook=notebook_path,
            state="unconfigured",
            generation=None,
            config_path=None,
            config_source=None,
            view_root=canonical_view_root(notebook_path),
            default_view=None,
            default_runtime=None,
            runtimes=(),
            bindings={},
            views=(),
            launch_requirements=resolve_launch_requirements(()),
        )

    discovered = discover_views(definition.view_root)
    owner_names = reconcile_view_owners(
        definition.view_root,
        set(discovered),
        refresh_names=lambda: set(discover_views(definition.view_root)),
    )
    if owner_names != set(discovered):
        discovered = discover_views(definition.view_root)
        if set(discovered) != owner_names:
            raise ConfigurationError(
                "The view catalog changed while Studio inspected it. Run again."
            )
    if discovered and definition.default_view not in discovered:
        raise ConfigurationError(
            f"Default view {definition.default_view!r} does not exist in "
            f"{definition.view_root}"
        )
    view_generations = {
        name: view_generation(view) for name, view in discovered.items()
    }
    generation = (
        workspace_catalog_generation(
            definition,
            discovered,
            view_generations,
            directory_generation(definition.view_root),
        )
        if discovered
        else definition.config_generation
    )
    view_records: list[ViewOverview] = []
    for name, view in discovered.items():
        inspection = inspect_view_project_sync(view)
        artifact = read_artifact_state(view, "development").artifact
        view_records.append(
            ViewOverview(
                name=name,
                generation=view_generations[name],
                path=view.root,
                default=name == definition.default_view,
                provider=view.provider,
                documents=tuple(
                    item.path.as_posix() for item in inspection.editor_documents
                ),
                artifact_revision=(
                    artifact.artifact_revision if artifact is not None else None
                ),
            )
        )
    views = tuple(view_records)
    return StudioOverview(
        notebook=notebook_path,
        state="ready" if views else "needs-view",
        generation=generation,
        config_path=definition.config_path,
        config_source=definition.config_source,
        view_root=definition.view_root,
        default_view=definition.default_view,
        default_runtime=definition.default_runtime,
        runtimes=definition.runtimes,
        bindings={name: str(ref) for name, ref in definition.cells.items()},
        views=views,
        launch_requirements=resolve_launch_requirements(
            project.provider for project in discovered.values()
        ),
    )
