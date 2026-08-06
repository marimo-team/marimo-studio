"""Validate configured views and their live notebook projections."""

from __future__ import annotations

from marimo_studio import _assets
from marimo_studio._workspace.bindings import resolve_studio
from marimo_studio._workspace.check_results import (
    error_result,
    projection_results,
    selected_views,
)
from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio._workspace.ports import NotebookInspector
from marimo_studio.errors import MarimoStudioError
from marimo_studio.types import CheckResult


def check_studio(
    studio: StudioWorkspace,
    *,
    inspect_notebook: NotebookInspector,
    view_name: str | None = None,
) -> tuple[CheckResult, ...]:
    """Validate the notebook, bindings, templates, and packaged runtime."""
    try:
        resolved = resolve_studio(
            studio,
            inspect_notebook=inspect_notebook,
            view_name=view_name,
        )
        selected = selected_views(resolved, view_name)
    except MarimoStudioError as error:
        return (error_result("configuration", error, studio),)
    results = [
        CheckResult(
            "notebook",
            "pass",
            f"Parsed {len(resolved.notebook.cells)} cells from {studio.notebook}",
        ),
        CheckResult(
            "bindings",
            "pass",
            f"Loaded {len(studio.cells)} configured cell aliases",
        ),
    ]
    for name in selected:
        view = resolved.views[name]
        if view.diagnostics:
            results.extend(projection_results(resolved, (name,)))
            continue
        cell_count = len(view.cell_aliases)
        value_count = len(view.value_bindings)
        results.append(
            CheckResult(
                f"view:{name}",
                "pass",
                (
                    f"Validated {cell_count} cell "
                    f"{'projection' if cell_count == 1 else 'projections'} and "
                    f"{value_count} value "
                    f"{'selector' if value_count == 1 else 'selectors'}"
                ),
            )
        )
    assets = _assets.runtime_assets_path()
    required = (
        "runtime.js",
        "runtime.css",
        "dev-reload.js",
        "studio.js",
        "studio.css",
    )
    missing = [name for name in required if not (assets / name).is_file()]
    results.append(
        CheckResult(
            "runtime-assets",
            "fail" if missing else "pass",
            (
                "Missing runtime assets: " + ", ".join(missing)
                if missing
                else "Browser runtime assets are available"
            ),
        )
    )
    return tuple(results)
