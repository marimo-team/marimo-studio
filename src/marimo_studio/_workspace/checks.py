"""Validate configured Views and their live notebook projections."""

from __future__ import annotations

from marimo_studio import _assets
from marimo_studio._compat.runtime_probe import probe_runtime
from marimo_studio._workspace.bindings import resolve_studio
from marimo_studio._workspace.models import ResolvedStudio, StudioConfig
from marimo_studio.errors import ConfigurationError
from marimo_studio.types import CheckResult


def _selected_views(
    resolved: ResolvedStudio,
    view_name: str | None,
) -> tuple[str, ...]:
    if view_name is None:
        return tuple(resolved.views)
    if view_name not in resolved.views:
        available = ", ".join(resolved.views)
        raise ConfigurationError(
            f"Unknown view {view_name!r}. Available views: {available}."
        )
    return (view_name,)


def check_studio(
    studio: StudioConfig,
    *,
    view_name: str | None = None,
) -> tuple[CheckResult, ...]:
    """Validate the notebook, bindings, templates, and packaged runtime."""
    try:
        resolved = resolve_studio(studio, view_name=view_name)
        selected = _selected_views(resolved, view_name)
    except ConfigurationError as error:
        return (CheckResult("configuration", "fail", str(error)),)
    results = [
        CheckResult(
            "notebook",
            "pass",
            f"Parsed {len(resolved.notebook.cells)} cells from {studio.notebook}",
        ),
        CheckResult(
            "bindings",
            "pass",
            f"Resolved {len(studio.cells)} configured cell aliases",
        ),
    ]
    for name in selected:
        view = resolved.views[name]
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


async def check_runtime_studio(
    studio: StudioConfig,
    *,
    view_name: str | None = None,
) -> tuple[CheckResult, ...]:
    """Execute the notebook and verify selected view cells and values."""
    try:
        resolved = resolve_studio(studio, view_name=view_name)
        selected = _selected_views(resolved, view_name)
    except ConfigurationError as error:
        return (CheckResult("runtime", "fail", str(error)),)

    aliases: set[str] = set()
    selectors: set[str] = set()
    projected: set[str] = set()
    for name in selected:
        view = resolved.views[name]
        aliases.update(view.cell_aliases)
        projected.update(view.cell_aliases)
        selectors.update(view.value_bindings)
    cells = {
        alias: resolved.aliases[alias]
        for alias in sorted(aliases)
        if alias in resolved.aliases
    }
    try:
        probe = await probe_runtime(
            studio.notebook,
            cell_ids=tuple(dict.fromkeys(cell.runtime_id for cell in cells.values())),
            variables=tuple(sorted(selectors)),
        )
    except Exception as error:
        return (
            CheckResult("runtime", "fail", f"Notebook runtime check failed: {error}"),
        )

    terminal = {"idle", "disabled-transitively"}
    results: list[CheckResult] = []
    for alias, cell in cells.items():
        runtime_cell = probe.cells[cell.runtime_id]
        name = f"runtime-cell:{alias}"
        if runtime_cell.errors:
            results.append(CheckResult(name, "fail", runtime_cell.errors[0]))
        elif runtime_cell.status not in terminal:
            results.append(
                CheckResult(
                    name,
                    "fail",
                    f"Cell ended in state {runtime_cell.status or 'missing'}",
                )
            )
        elif alias in projected and not runtime_cell.outputs:
            results.append(
                CheckResult(name, "fail", "Projected cell produced no runtime output")
            )
        else:
            mimes = ", ".join(
                dict.fromkeys(
                    output.mimetype
                    for output in runtime_cell.outputs
                    if not output.empty
                )
            )
            results.append(
                CheckResult(
                    name,
                    "pass",
                    f"Cell completed{f' with {mimes}' if mimes else ''}",
                )
            )
    for selector in sorted(selectors):
        error = probe.values.errors.get(selector)
        if error is not None:
            results.append(
                CheckResult(
                    f"runtime-value:{selector}",
                    "fail",
                    f"{error.code}: {error.message}",
                )
            )
        elif selector not in probe.values.values:
            results.append(
                CheckResult(
                    f"runtime-value:{selector}",
                    "fail",
                    "Kernel omitted the requested value",
                )
            )
        else:
            results.append(
                CheckResult(
                    f"runtime-value:{selector}",
                    "pass",
                    "Kernel value resolved to JSON data",
                )
            )
    if not results:
        results.append(CheckResult("runtime", "pass", "Notebook run completed"))
    return tuple(results)
