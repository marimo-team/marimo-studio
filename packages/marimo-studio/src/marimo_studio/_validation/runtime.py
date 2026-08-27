"""Validate bounded view projections through one complete notebook run."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping

from marimo_studio._notebook.ports import LiveNotebookRunner, NotebookInspector
from marimo_studio._notebook.records import CellSpec
from marimo_studio._projections.resolution import ResolvedProjection
from marimo_studio._projections.resolved import ResolvedStudio
from marimo_studio._projections.runtime_records import (
    RenderedOutput,
    RuntimeCell,
    ValueReadError,
)
from marimo_studio._projections.studio import resolve_studio
from marimo_studio._validation.check_results import (
    error_result,
    projection_results,
    runtime_cell_details,
    runtime_output_hint,
    runtime_projection_details,
    runtime_value_hint,
    selected_views,
    source,
)
from marimo_studio._validation.results import CheckResult
from marimo_studio._views.inspection import inspect_view_project_sync
from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio.errors import MarimoStudioError, ViewNotFoundError
from marimo_studio.view_providers import MountDeclaration


def _cell_details(
    studio: StudioWorkspace,
    target: str,
    cell: CellSpec,
    hint: str,
    views: tuple[str, ...],
) -> dict[str, object]:
    return runtime_cell_details(
        studio,
        target,
        cell,
        hint,
        projection="cell",
        views=views,
    )


async def run_runtime_checks(
    studio: StudioWorkspace,
    *,
    inspect_notebook: NotebookInspector,
    view_name: str | None,
    probe_runtime: LiveNotebookRunner,
    timeout: float,
    published_mounts: Mapping[str, tuple[MountDeclaration, ...]] | None = None,
) -> tuple[CheckResult, ...]:
    try:
        if view_name is not None and view_name not in studio.views:
            raise ViewNotFoundError(view_name, available=tuple(studio.views))
        view_names = (view_name,) if view_name is not None else tuple(studio.views)
        if published_mounts is None:
            inspections = await asyncio.gather(
                *(
                    asyncio.to_thread(inspect_view_project_sync, studio.views[name])
                    for name in view_names
                )
            )
            published_mounts = {
                name: inspection.mounts
                for name, inspection in zip(view_names, inspections, strict=True)
            }
        resolved = resolve_studio(
            studio,
            inspect_notebook=inspect_notebook,
            view_name=view_name,
            published_mounts=published_mounts,
        )
        selected = selected_views(resolved, view_name)
    except MarimoStudioError as error:
        return (error_result("runtime", error, studio),)

    diagnostics = projection_results(resolved, selected)
    if any(result.status == "fail" for result in diagnostics):
        return diagnostics

    cells: dict[str, ResolvedProjection] = {}
    values: dict[str, list[tuple[str, ResolvedProjection]]] = {}
    outputs: dict[str, list[tuple[str, ResolvedProjection]]] = {}
    output_groups: list[tuple[str, ...]] = []
    for name in selected:
        view_outputs: list[str] = []
        for projection in resolved.views[name].projections:
            target = projection.request.target
            if projection.kind == "cell":
                cells.setdefault(target, projection)
            elif projection.kind == "value":
                values.setdefault(target, []).append((name, projection))
            else:
                outputs.setdefault(target, []).append((name, projection))
                view_outputs.append(target)
        if view_outputs:
            output_groups.append(tuple(dict.fromkeys(sorted(view_outputs))))

    notebook_cells = resolved.notebook.by_ref()
    try:
        probe = await probe_runtime(
            studio.notebook,
            cell_ids=tuple(
                dict.fromkeys(
                    notebook_cells[item.producer].runtime_id for item in cells.values()
                )
            ),
            variables=tuple(sorted(values)),
            output_selector_groups=tuple(output_groups),
            show_tracebacks=True,
            timeout=timeout,
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

    results = _cell_results(studio, resolved, selected, cells, probe.cells)
    results.extend(
        _value_results(studio, values, probe.values.values, probe.values.errors)
    )
    results.extend(
        _output_results(studio, outputs, probe.outputs.outputs, probe.outputs.errors)
    )
    if not results:
        results.append(CheckResult("runtime", "pass", "Notebook run completed"))
    return tuple(results)


def _cell_results(
    studio: StudioWorkspace,
    resolved: ResolvedStudio,
    selected: tuple[str, ...],
    projections: dict[str, ResolvedProjection],
    runtime_cells: Mapping[str, RuntimeCell],
) -> list[CheckResult]:
    cells = resolved.notebook.by_ref()
    results: list[CheckResult] = []
    for target, projection in sorted(projections.items()):
        cell = cells[projection.producer]
        runtime_cell = runtime_cells[cell.runtime_id]
        views = tuple(
            name
            for name in selected
            if any(
                item.kind == "cell" and item.request.target == target
                for item in resolved.views[name].projections
            )
        )
        name = f"runtime-cell:{target}"
        if runtime_cell.errors:
            results.append(
                CheckResult(
                    name,
                    "fail",
                    runtime_cell.errors[0],
                    code="cell-execution-error",
                    details=_cell_details(
                        studio,
                        target,
                        cell,
                        "Fix the cell in Marimo, then rerun the check.",
                        views,
                    ),
                )
            )
            continue
        if cell.config.disabled or runtime_cell.status == "disabled-transitively":
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
                    details=_cell_details(
                        studio,
                        target,
                        cell,
                        "Enable the cell in Marimo or remove its projection."
                        if explicit
                        else (
                            "Enable the disabled upstream cell in Marimo or "
                            "remove this projection."
                        ),
                        views,
                    ),
                )
            )
            continue
        if runtime_cell.status != "idle":
            results.append(
                CheckResult(
                    name,
                    "fail",
                    f"Cell ended in state {runtime_cell.status or 'missing'}",
                    code="cell-runtime-incomplete",
                    details=_cell_details(
                        studio,
                        target,
                        cell,
                        "Run the cell to a terminal state, then rerun the check.",
                        views,
                    ),
                )
            )
            continue
        if not runtime_cell.outputs:
            results.append(
                CheckResult(
                    name,
                    "fail",
                    "Projected cell produced no runtime output",
                    code="projected-cell-empty",
                    details=_cell_details(
                        studio,
                        target,
                        cell,
                        "Return a display value from the cell or remove its "
                        "projection.",
                        views,
                    ),
                )
            )
            continue
        mimes = ", ".join(
            dict.fromkeys(
                output.mimetype for output in runtime_cell.outputs if not output.empty
            )
        )
        results.append(
            CheckResult(
                name,
                "pass",
                f"Cell completed{f' with {mimes}' if mimes else ''}",
            )
        )
    return results


def _value_results(
    studio: StudioWorkspace,
    projections: dict[str, list[tuple[str, ResolvedProjection]]],
    values: Mapping[str, object],
    errors: Mapping[str, ValueReadError],
) -> list[CheckResult]:
    results: list[CheckResult] = []
    for target, bindings in sorted(projections.items()):
        error = errors.get(target)
        if error is not None:
            results.append(
                CheckResult(
                    f"runtime-value:{target}",
                    "fail",
                    error.message,
                    code=error.code,
                    details=runtime_projection_details(
                        studio,
                        target,
                        tuple(bindings),
                        runtime_value_hint(error.code),
                    ),
                )
            )
        elif target not in values:
            results.append(
                CheckResult(
                    f"runtime-value:{target}",
                    "fail",
                    "Kernel omitted the requested value",
                    code="missing-value-response",
                    details=runtime_projection_details(
                        studio,
                        target,
                        tuple(bindings),
                        "Rerun the defining cell, then rerun the check.",
                    ),
                )
            )
        else:
            results.append(
                CheckResult(
                    f"runtime-value:{target}",
                    "pass",
                    "Kernel value resolved to JSON data",
                )
            )
    return results


def _output_results(
    studio: StudioWorkspace,
    projections: dict[str, list[tuple[str, ResolvedProjection]]],
    outputs: Mapping[str, RenderedOutput],
    errors: Mapping[str, ValueReadError],
) -> list[CheckResult]:
    results: list[CheckResult] = []
    response_error = errors.get("*")
    for target, bindings in sorted(projections.items()):
        error = errors.get(target) or response_error
        if error is not None:
            results.append(
                CheckResult(
                    f"runtime-output:{target}",
                    "fail",
                    error.message,
                    code=error.code,
                    details=runtime_projection_details(
                        studio,
                        target,
                        tuple(bindings),
                        runtime_output_hint(error.code),
                    ),
                )
            )
        elif target not in outputs:
            results.append(
                CheckResult(
                    f"runtime-output:{target}",
                    "fail",
                    "Kernel omitted the requested output",
                    code="missing-output-response",
                    details=runtime_projection_details(
                        studio,
                        target,
                        tuple(bindings),
                        "Rerun the defining cell, then rerun the check.",
                    ),
                )
            )
        else:
            output = outputs[target]
            results.append(
                CheckResult(
                    f"runtime-output:{target}",
                    "pass",
                    f"Kernel output rendered as {output.mimetype}",
                )
            )
    return results
