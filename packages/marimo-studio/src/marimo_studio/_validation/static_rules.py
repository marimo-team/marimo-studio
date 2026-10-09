"""Validate configured views and their live notebook projections."""

from __future__ import annotations

from collections.abc import Mapping

import marimo_studio._delivery.assets as _assets
from marimo_studio._notebook.ports import NotebookInspector
from marimo_studio._projections.ports import ViewSiteInspector
from marimo_studio._projections.studio import resolve_studio
from marimo_studio._validation.check_results import (
    error_result,
    projection_results,
    selected_views,
)
from marimo_studio._validation.results import CheckResult
from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio.errors import MarimoStudioError
from marimo_studio.view_providers._artifact_sites import ArtifactSite


def check_studio(
    studio: StudioWorkspace,
    *,
    inspect_notebook: NotebookInspector,
    inspect_sites: ViewSiteInspector,
    view_name: str | None = None,
    published_sites: Mapping[str, tuple[ArtifactSite, ...]] | None = None,
) -> tuple[CheckResult, ...]:
    """Validate the notebook, view projects, projections, and packaged runtime."""
    try:
        resolved = resolve_studio(
            studio,
            inspect_notebook=inspect_notebook,
            inspect_sites=inspect_sites,
            view_name=view_name,
            published_sites=published_sites,
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
        counts = {
            kind: sum(site.kind == kind for site in view.sites)
            for kind in ("cell", "output", "value")
        }
        results.append(
            CheckResult(
                f"view:{name}",
                "pass",
                (
                    f"Validated {counts['cell']} cell, {counts['output']} output, "
                    f"and {counts['value']} value projection sites"
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
