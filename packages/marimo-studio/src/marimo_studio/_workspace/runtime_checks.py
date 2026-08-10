"""Execute a notebook and validate its runtime projections."""

from __future__ import annotations

from marimo_studio._workspace.bindings import resolve_studio
from marimo_studio._workspace.check_results import (
    error_result,
    projection_results,
    runtime_cell_details,
    runtime_output_hint,
    runtime_value_details,
    runtime_value_hint,
    selected_views,
    source,
)
from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio._workspace.ports import NotebookInspector, RuntimeProber
from marimo_studio.errors import MarimoStudioError
from marimo_studio.types import CheckResult, ValueBinding


async def run_runtime_checks(
    studio: StudioWorkspace,
    *,
    inspect_notebook: NotebookInspector,
    view_name: str | None,
    probe_runtime: RuntimeProber,
) -> tuple[CheckResult, ...]:
    try:
        resolved = resolve_studio(
            studio,
            inspect_notebook=inspect_notebook,
            view_name=view_name,
        )
        selected = selected_views(resolved, view_name)
    except MarimoStudioError as error:
        return (error_result("runtime", error, studio),)

    diagnostics = projection_results(resolved, selected)
    if any(result.status == "fail" for result in diagnostics):
        return diagnostics

    aliases: set[str] = set()
    selectors: set[str] = set()
    output_selectors: set[str] = set()
    cell_views: dict[str, list[str]] = {}
    value_views: dict[str, list[str]] = {}
    value_bindings: dict[str, list[ValueBinding]] = {}
    output_views: dict[str, list[str]] = {}
    output_bindings: dict[str, list[ValueBinding]] = {}
    for name in selected:
        view = resolved.views[name]
        aliases.update(view.cell_aliases)
        selectors.update(view.value_bindings)
        output_selectors.update(view.output_bindings)
        for alias in view.cell_aliases:
            cell_views.setdefault(alias, []).append(name)
        for selector in view.value_bindings:
            value_views.setdefault(selector, []).append(name)
        for selector, binding in view.value_bindings.items():
            value_bindings.setdefault(selector, []).append(binding)
        for selector in view.output_bindings:
            output_views.setdefault(selector, []).append(name)
        for selector, binding in view.output_bindings.items():
            output_bindings.setdefault(selector, []).append(binding)
    cells = {
        alias: resolved.aliases[alias]
        for alias in sorted(aliases)
        if alias in resolved.aliases
    }
    try:
        output_selector_groups = tuple(
            tuple(sorted(resolved.views[name].output_bindings))
            for name in selected
            if resolved.views[name].output_bindings
        )
        probe = await probe_runtime(
            studio.notebook,
            cell_ids=tuple(dict.fromkeys(cell.runtime_id for cell in cells.values())),
            variables=tuple(sorted(selectors)),
            output_selector_groups=output_selector_groups,
            show_tracebacks=True,
        )
    except MarimoStudioError as error:
        return (error_result("runtime", error, studio),)
    except Exception as error:
        return (
            CheckResult(
                "runtime",
                "fail",
                f"Notebook runtime check failed: {error}",
                code="runtime-check-failed",
                details={"source": source(studio.notebook)},
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
                    details=runtime_cell_details(
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
                    details=runtime_cell_details(
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
                    details=runtime_cell_details(
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
                    details=runtime_cell_details(
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
                    details=runtime_value_details(
                        studio,
                        selector,
                        bindings,
                        runtime_value_hint(error.code),
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
                    details=runtime_value_details(
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
    for selector in sorted(output_selectors):
        bindings = tuple(output_bindings[selector])
        error = probe.outputs.errors.get(selector) or probe.outputs.errors.get("*")
        if error is not None:
            results.append(
                CheckResult(
                    f"runtime-output:{selector}",
                    "fail",
                    error.message,
                    code=error.code,
                    details=runtime_value_details(
                        studio,
                        selector,
                        bindings,
                        runtime_output_hint(error.code),
                        projection="output",
                        views=tuple(output_views[selector]),
                    ),
                )
            )
        elif selector not in probe.outputs.outputs:
            results.append(
                CheckResult(
                    f"runtime-output:{selector}",
                    "fail",
                    "Kernel omitted the requested output",
                    code="missing-output-response",
                    details=runtime_value_details(
                        studio,
                        selector,
                        bindings,
                        "Rerun the defining cell, then rerun the check.",
                        projection="output",
                        views=tuple(output_views[selector]),
                    ),
                )
            )
        else:
            output = probe.outputs.outputs[selector]
            results.append(
                CheckResult(
                    f"runtime-output:{selector}",
                    "pass",
                    f"Kernel output rendered as {output.mimetype}",
                )
            )
    if not results:
        results.append(CheckResult("runtime", "pass", "Notebook run completed"))
    return tuple(results)
