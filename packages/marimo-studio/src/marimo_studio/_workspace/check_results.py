"""Build structured diagnostics for static and runtime checks."""

from __future__ import annotations

from marimo_studio._workspace.models import ResolvedStudio, StudioWorkspace
from marimo_studio.errors import (
    ConfigurationError,
    MarimoStudioError,
    NotebookSourceError,
)
from marimo_studio.types import CellSpec, CheckResult, ValueBinding


def selected_views(
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


def projection_results(
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


def source(path: object, cell: CellSpec | None = None) -> dict[str, object]:
    result: dict[str, object] = {"path": str(path)}
    if cell is not None:
        result.update(
            line=cell.source.start_line,
            column=cell.source.start_column + 1,
        )
    return result


def error_result(
    name: str,
    error: MarimoStudioError,
    studio: StudioWorkspace,
) -> CheckResult:
    details = error.diagnostic_details()
    if isinstance(error, NotebookSourceError):
        details.setdefault("source", source(studio.notebook))
    if error.public_hint:
        details["hint"] = error.public_hint
    return CheckResult(
        name=name,
        status="fail",
        message=str(error),
        code=error.code,
        details=details or None,
    )


def runtime_cell_details(
    studio: StudioWorkspace,
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
        "source": source(studio.notebook, cell),
        "hint": hint,
    }
    details["view" if len(views) == 1 else "views"] = (
        views[0] if len(views) == 1 else list(views)
    )
    return details


def runtime_value_details(
    studio: StudioWorkspace,
    target: str,
    bindings: tuple[ValueBinding, ...],
    hint: str,
    *,
    projection: str = "value",
    views: tuple[str, ...],
) -> dict[str, object]:
    binding = bindings[0]
    details: dict[str, object] = {
        "projection": projection,
        "target": target,
        "source": {
            "path": str(binding.source),
            "line": binding.line,
            "column": binding.column,
        },
        "definition": source(studio.notebook, binding.cell),
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
    details["view" if len(views) == 1 else "views"] = (
        views[0] if len(views) == 1 else list(views)
    )
    return details


def runtime_value_hint(code: str) -> str:
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


def runtime_output_hint(code: str) -> str:
    if code == "value-path-unavailable":
        return (
            "Fix the marimo-output selector in the view template or the value "
            "shape in Marimo, then rerun the check."
        )
    if code == "missing-variable":
        return (
            "Restore the defining notebook variable or update the marimo-output "
            "selector, then rerun the check."
        )
    if code in {"output-too-large", "response-too-large"}:
        return "Project a smaller rich output, then rerun the check."
    return (
        "Fix the marimo-output selector in the view template or its defining "
        "notebook cell, then rerun the check."
    )
