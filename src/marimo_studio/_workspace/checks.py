"""Validate configured Views and their live notebook projections."""

from __future__ import annotations

from marimo_studio import _assets
from marimo_studio._compat.runtime_probe import probe_runtime
from marimo_studio._workspace.bindings import resolve_studio
from marimo_studio._workspace.models import ResolvedStudio, StudioConfig
from marimo_studio.errors import (
    ConfigurationError,
    MarimoStudioError,
    NotebookSourceError,
)
from marimo_studio.types import CellSpec, CheckResult, ValueBinding


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


def _projection_results(
    resolved: ResolvedStudio,
    selected: tuple[str, ...],
) -> tuple[CheckResult, ...]:
    return tuple(
        CheckResult(
            name=f"view:{name}:{diagnostic.projection}:{diagnostic.target}",
            status="fail" if diagnostic.severity == "error" else "warn",
            message=diagnostic.message,
            code=diagnostic.code,
            details=diagnostic.details(),
        )
        for name in selected
        for diagnostic in resolved.views[name].diagnostics
    )


def _source(path: object, cell: CellSpec | None = None) -> dict[str, object]:
    source: dict[str, object] = {"path": str(path)}
    if cell is not None:
        source.update(
            line=cell.source.start_line,
            column=cell.source.start_column + 1,
        )
    return source


def _error_result(
    name: str,
    error: MarimoStudioError,
    studio: StudioConfig,
) -> CheckResult:
    details = error.diagnostic_details()
    if isinstance(error, NotebookSourceError):
        details.setdefault("source", _source(studio.notebook))
    if error.public_hint:
        details["hint"] = error.public_hint
    return CheckResult(
        name=name,
        status="fail",
        message=str(error),
        code=error.code,
        details=details or None,
    )


def _runtime_details(
    studio: StudioConfig,
    target: str,
    cell: CellSpec,
    hint: str,
    *,
    projection: str,
    views: tuple[str, ...],
) -> dict[str, object]:
    details: dict[str, object] = {
        "projection": projection,
        "target": target,
        "source": _source(studio.notebook, cell),
        "hint": hint,
    }
    if len(views) == 1:
        details["view"] = views[0]
    else:
        details["views"] = list(views)
    return details


def _runtime_value_details(
    studio: StudioConfig,
    target: str,
    bindings: tuple[ValueBinding, ...],
    hint: str,
    *,
    views: tuple[str, ...],
) -> dict[str, object]:
    binding = bindings[0]
    details: dict[str, object] = {
        "projection": "value",
        "target": target,
        "source": {
            "path": str(binding.source),
            "line": binding.line,
            "column": binding.column,
        },
        "definition": _source(studio.notebook, binding.cell),
        "hint": hint,
    }
    if len(bindings) > 1:
        details["sources"] = [
            {
                "path": str(candidate.source),
                "line": candidate.line,
                "column": candidate.column,
            }
            for candidate in bindings
        ]
    if len(views) == 1:
        details["view"] = views[0]
    else:
        details["views"] = list(views)
    return details


def _runtime_value_hint(code: str) -> str:
    if code == "value-path-unavailable":
        return (
            "Fix the mo-value selector in the view template or the value shape "
            "in Marimo, then rerun the check."
        )
    if code == "missing-variable":
        return (
            "Restore the defining notebook variable or update the mo-value "
            "selector, then rerun the check."
        )
    if code == "not-json-serializable":
        return (
            "Convert the projected value to JSON data in Marimo or project its "
            "cell output."
        )
    if code == "value-too-large":
        return "Project a smaller JSON value or render the defining cell."
    return (
        "Fix the mo-value selector in the view template or its defining "
        "notebook cell, then rerun the check."
    )


def check_studio(
    studio: StudioConfig,
    *,
    view_name: str | None = None,
) -> tuple[CheckResult, ...]:
    """Validate the notebook, bindings, templates, and packaged runtime."""
    try:
        resolved = resolve_studio(studio, view_name=view_name)
        selected = _selected_views(resolved, view_name)
    except MarimoStudioError as error:
        return (_error_result("configuration", error, studio),)
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
            results.extend(_projection_results(resolved, (name,)))
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


async def check_runtime_studio(
    studio: StudioConfig,
    *,
    view_name: str | None = None,
) -> tuple[CheckResult, ...]:
    """Execute the notebook and verify selected view cells and values."""
    try:
        resolved = resolve_studio(studio, view_name=view_name)
        selected = _selected_views(resolved, view_name)
    except MarimoStudioError as error:
        return (_error_result("runtime", error, studio),)

    projection_results = _projection_results(resolved, selected)
    if any(result.status == "fail" for result in projection_results):
        return projection_results

    aliases: set[str] = set()
    selectors: set[str] = set()
    cell_views: dict[str, list[str]] = {}
    value_views: dict[str, list[str]] = {}
    value_bindings: dict[str, list[ValueBinding]] = {}
    for name in selected:
        view = resolved.views[name]
        aliases.update(view.cell_aliases)
        selectors.update(view.value_bindings)
        for alias in view.cell_aliases:
            cell_views.setdefault(alias, []).append(name)
        for selector in view.value_bindings:
            value_views.setdefault(selector, []).append(name)
        for selector, binding in view.value_bindings.items():
            value_bindings.setdefault(selector, []).append(binding)
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
    except MarimoStudioError as error:
        return (_error_result("runtime", error, studio),)
    except Exception as error:
        return (
            CheckResult(
                "runtime",
                "fail",
                f"Notebook runtime check failed: {error}",
                code="runtime-check-failed",
                details={"source": _source(studio.notebook)},
            ),
        )

    results: list[CheckResult] = []
    for alias, cell in cells.items():
        runtime_cell = probe.cells[cell.runtime_id]
        name = f"runtime-cell:{alias}"
        if runtime_cell.errors:
            results.append(
                CheckResult(
                    name,
                    "fail",
                    runtime_cell.errors[0],
                    code="cell-execution-error",
                    details=_runtime_details(
                        studio,
                        alias,
                        cell,
                        "Fix the cell in Marimo, then rerun the check.",
                        projection="cell",
                        views=tuple(cell_views[alias]),
                    ),
                )
            )
        elif cell.config.disabled or runtime_cell.status == "disabled-transitively":
            explicit = cell.config.disabled
            results.append(
                CheckResult(
                    name,
                    "fail",
                    (
                        "Projected cell is disabled"
                        if explicit
                        else "Projected cell has a disabled upstream dependency"
                    ),
                    code="cell-disabled",
                    details=_runtime_details(
                        studio,
                        alias,
                        cell,
                        (
                            "Enable the cell in Marimo or remove its projection."
                            if explicit
                            else "Enable the disabled upstream cell in Marimo "
                            "or remove this projection."
                        ),
                        projection="cell",
                        views=tuple(cell_views[alias]),
                    ),
                )
            )
        elif runtime_cell.status != "idle":
            results.append(
                CheckResult(
                    name,
                    "fail",
                    f"Cell ended in state {runtime_cell.status or 'missing'}",
                    code="cell-runtime-incomplete",
                    details=_runtime_details(
                        studio,
                        alias,
                        cell,
                        "Run the cell to a terminal state, then rerun the check.",
                        projection="cell",
                        views=tuple(cell_views[alias]),
                    ),
                )
            )
        elif not runtime_cell.outputs:
            results.append(
                CheckResult(
                    name,
                    "fail",
                    "Projected cell produced no runtime output",
                    code="projected-cell-empty",
                    details=_runtime_details(
                        studio,
                        alias,
                        cell,
                        "Return a display value from the cell or remove "
                        "its projection.",
                        projection="cell",
                        views=tuple(cell_views[alias]),
                    ),
                )
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
        bindings = tuple(value_bindings[selector])
        error = probe.values.errors.get(selector)
        if error is not None:
            results.append(
                CheckResult(
                    f"runtime-value:{selector}",
                    "fail",
                    error.message,
                    code=error.code,
                    details=_runtime_value_details(
                        studio,
                        selector,
                        bindings,
                        _runtime_value_hint(error.code),
                        views=tuple(value_views[selector]),
                    ),
                )
            )
        elif selector not in probe.values.values:
            results.append(
                CheckResult(
                    f"runtime-value:{selector}",
                    "fail",
                    "Kernel omitted the requested value",
                    code="missing-value-response",
                    details=_runtime_value_details(
                        studio,
                        selector,
                        bindings,
                        "Rerun the defining cell, then rerun the check.",
                        views=tuple(value_views[selector]),
                    ),
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
