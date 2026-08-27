"""Resolve notebook symbols, provider sites, and configured cell aliases."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from marimo_studio._notebook.cell_refs import cell_ref_candidates, safe_cell_ref_matches
from marimo_studio._notebook.ports import NotebookInspector
from marimo_studio._notebook.records import CellSpec
from marimo_studio._projections.ports import ViewMountInspector
from marimo_studio._projections.resolution import (
    ProjectionRequest,
    ProjectionResolutionError,
    ResolvedProjection,
    resolve_projection,
    validate_mount_declaration,
)
from marimo_studio._projections.resolved import (
    ProjectionDiagnostic,
    ResolvedStudio,
    ResolvedView,
)
from marimo_studio._projections.symbol_graph import (
    NotebookSymbolGraph,
    build_notebook_symbol_graph,
)
from marimo_studio._projections.values import MAX_OUTPUT_SELECTORS
from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio.errors import ConfigurationError, ViewNotFoundError, ViewProjectError
from marimo_studio.view_providers import (
    MountDeclaration,
    ProjectionKind,
    ViewProject,
)


@dataclass(frozen=True)
class _AliasFailure:
    code: str
    message: str
    hint: str


def _diagnostic(
    view: ViewProject,
    site: MountDeclaration,
    *,
    code: str,
    message: str,
    hint: str,
    projection: ProjectionKind,
    target: str,
) -> ProjectionDiagnostic:
    return ProjectionDiagnostic(
        code=code,
        severity="error",
        message=message,
        hint=hint,
        view=view.name,
        projection=projection,
        target=target,
        source=view.root / site.source.path,
        line=site.source.line,
        column=site.source.column,
        site_id=site.id,
    )


def _projection_hint(error: ProjectionResolutionError) -> str:
    if error.code.endswith("-not-found"):
        return "Name the notebook cell or define the variable, then update the view."
    if error.code.endswith("-ambiguous"):
        return "Give the projection target one notebook producer."
    if error.code == "projection-target-invalid":
        return (
            "Use a notebook variable followed by supported attribute or item selectors."
        )
    if error.code == "projection-target-not-allowed":
        return "Use a target declared by this source site."
    return "Fix the provider projection site, then build the view again."


def _resolve_view(
    view: ViewProject,
    graph: NotebookSymbolGraph,
    alias_failures: dict[str, _AliasFailure],
    sites: tuple[MountDeclaration, ...],
) -> ResolvedView:
    site_ids = [site.id for site in sites]
    if len(site_ids) != len(set(site_ids)):
        raise ViewProjectError(
            f"{view.manifest}: provider projection site IDs must be unique",
            source=view.manifest,
        )
    bounded_output_targets = {
        target
        for site in sites
        if site.kind == "output" and site.allowed_targets is not None
        for target in site.allowed_targets
    }
    if len(bounded_output_targets) > MAX_OUTPUT_SELECTORS:
        site = next(
            site for site in sites if site.kind == "output" and site.allowed_targets
        )
        raise ViewProjectError(
            f"{site.source.path}: a view may contain at most "
            f"{MAX_OUTPUT_SELECTORS} output selectors",
            source=view.root / site.source.path,
            line=site.source.line,
            column=site.source.column,
        )
    diagnostics: list[ProjectionDiagnostic] = []
    projections: list[ResolvedProjection] = []
    ordered_sites = sorted(
        sites,
        key=lambda item: (
            item.source.path.as_posix(),
            item.source.line,
            item.source.column,
            item.id,
        ),
    )
    for site in ordered_sites:
        try:
            validate_mount_declaration(site)
        except ProjectionResolutionError as error:
            diagnostics.append(
                _diagnostic(
                    view,
                    site,
                    code=error.code,
                    message=str(error),
                    hint=_projection_hint(error),
                    projection=site.kind,
                    target="",
                )
            )
            continue
        if site.allowed_targets is None:
            continue
        for index, target in enumerate(site.allowed_targets):
            try:
                projections.append(
                    resolve_projection(
                        graph,
                        sites,
                        ProjectionRequest(
                            site_id=site.id,
                            instance_id=f"static:{site.id}:{index}",
                            target=target,
                        ),
                    )
                )
            except ProjectionResolutionError as error:
                alias_failure = (
                    alias_failures.get(target) if site.kind == "cell" else None
                )
                diagnostics.append(
                    _diagnostic(
                        view,
                        site,
                        code=alias_failure.code if alias_failure else error.code,
                        message=alias_failure.message if alias_failure else str(error),
                        hint=(
                            alias_failure.hint
                            if alias_failure
                            else _projection_hint(error)
                        ),
                        projection=site.kind,
                        target=target,
                    )
                )
    return ResolvedView(
        view=view,
        mounts=sites,
        projections=tuple(projections),
        diagnostics=tuple(diagnostics),
    )


def _resolve_aliases(
    studio: StudioWorkspace,
    notebook_cells: tuple[CellSpec, ...],
    native_aliases: dict[str, CellSpec],
) -> tuple[dict[str, CellSpec], dict[str, _AliasFailure]]:
    aliases = dict(native_aliases)
    failures: dict[str, _AliasFailure] = {}
    cells_by_id = {cell.runtime_id: cell for cell in notebook_cells}
    resolved_ids = safe_cell_ref_matches(
        studio.cells,
        ((cell.ref, cell.runtime_id) for cell in notebook_cells),
    )
    for alias, ref in studio.cells.items():
        native = aliases.get(alias)
        matches = cell_ref_candidates(
            ref,
            ((cell.ref, cell) for cell in notebook_cells),
        )
        cell = cells_by_id.get(resolved_ids.get(alias, ""))
        if cell is None and matches:
            if native is not None:
                continue
            message = (
                f"Cell alias {alias!r} matches more than one notebook cell."
                if len(matches) > 1
                else f"Cell alias {alias!r} conflicts with another cell binding."
            )
            failures[alias] = _AliasFailure(
                "cell-binding-ambiguous",
                message,
                "Inspect the notebook, then bind this alias again with --overwrite.",
            )
            aliases.pop(alias, None)
            continue
        if cell is None:
            if native is not None:
                continue
            failures[alias] = _AliasFailure(
                "cell-binding-stale",
                f"Cell alias {alias!r} does not match a notebook cell.",
                "Inspect the notebook, then bind this alias again with --overwrite.",
            )
            aliases.pop(alias, None)
            continue
        if native is not None and native.runtime_id != cell.runtime_id:
            failures[alias] = _AliasFailure(
                "cell-binding-conflict",
                f"Cell alias {alias!r} conflicts with a named notebook cell.",
                "Rename the notebook cell or choose a different configured alias.",
            )
            aliases.pop(alias, None)
            continue
        aliases[alias] = cell
    return aliases, failures


def resolve_studio(
    studio: StudioWorkspace,
    *,
    inspect_notebook: NotebookInspector,
    inspect_mounts: ViewMountInspector | None = None,
    include_code: bool = False,
    view_name: str | None = None,
    published_mounts: Mapping[str, tuple[MountDeclaration, ...]] | None = None,
) -> ResolvedStudio:
    """Resolve provider projection sites against the current notebook graph."""
    if not studio.notebook.is_file():
        raise ConfigurationError(f"Notebook does not exist: {studio.notebook}")
    notebook = inspect_notebook(studio.notebook, include_code=include_code)
    aliases, alias_failures = _resolve_aliases(
        studio,
        notebook.cells,
        notebook.named_cells(),
    )

    symbols = build_notebook_symbol_graph(notebook, aliases)
    if view_name is not None and view_name not in studio.views:
        raise ViewNotFoundError(view_name, available=tuple(studio.views))
    selected_views = (
        {view_name: studio.views[view_name]} if view_name is not None else studio.views
    )
    if published_mounts is None:
        if inspect_mounts is None:
            raise RuntimeError("View mount inspection is required")
        site_catalogs: Mapping[str, tuple[MountDeclaration, ...]] = {
            name: inspect_mounts(view) for name, view in selected_views.items()
        }
    else:
        missing = set(selected_views).difference(published_mounts)
        if missing:
            raise ConfigurationError(
                f"Projection sites are missing for view {sorted(missing)[0]!r}"
            )
        site_catalogs = published_mounts
    resolved_views = {
        name: _resolve_view(
            view,
            symbols,
            alias_failures,
            site_catalogs[name],
        )
        for name, view in selected_views.items()
    }
    return ResolvedStudio(studio, notebook, symbols, aliases, resolved_views)
