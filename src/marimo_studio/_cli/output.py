"""Render CLI results as human text or stable JSON."""

from __future__ import annotations

import json
from typing import Any

from marimo_studio._cli.print import echo, green, light_blue, red, yellow
from marimo_studio._workspace.launch import LaunchPlan
from marimo_studio._workspace.models import (
    BindingResult,
    StudioConfig,
    ViewSetupResult,
)
from marimo_studio.inspect import RuntimeInspection
from marimo_studio.types import CellSpec, CheckResult, NotebookSpec


def echo_error(message: str) -> None:
    """Write a human error to stderr."""
    echo(red(message), err=True)


def echo_json(value: Any) -> None:
    """Write a deterministic JSON result to stdout."""
    echo(json.dumps(value, indent=2, sort_keys=True))


def render_view_setup(result: ViewSetupResult) -> None:
    """Write a view setup result in human text."""
    verb = "Would add" if result.dry_run else "Added"
    echo(f"{green(verb)} view {result.name} at {result.root}")
    for path in result.created:
        echo(f"  {light_blue('create')} {path}")
    for path in result.updated:
        echo(f"  {light_blue('update')} {path}")


def view_list_payload(studio: StudioConfig) -> dict[str, object]:
    """Serialize the configured view inventory."""
    return {
        "schema": 1,
        "notebook": str(studio.notebook),
        "default_view": studio.default_view,
        "views": [
            {
                "name": name,
                "path": str(view.root),
                "default": name == studio.default_view,
            }
            for name, view in studio.views.items()
        ],
    }


def render_view_list(studio: StudioConfig) -> None:
    """Write configured views in human text."""
    for name, view in studio.views.items():
        suffix = " (default)" if name == studio.default_view else ""
        echo(f"{light_blue(name)}{suffix}\n  {view.root}")


def render_binding(result: BindingResult, *, dry_run: bool) -> None:
    """Write a cell binding result in human text."""
    if result.previous_ref == result.cell.ref:
        echo(f"{result.alias} already points to cell {result.cell.index}")
        return
    verb = "Would bind" if dry_run else "Bound"
    echo(
        f"{green(verb)} {result.alias} to cell {result.cell.index} "
        f"({result.cell.source.start_line}-{result.cell.source.end_line})"
    )


def binding_payload(result: BindingResult, *, dry_run: bool) -> dict[str, Any]:
    """Serialize a cell binding result."""
    payload = result.to_dict()
    payload["dry_run"] = dry_run
    return payload


def inspection_payload(
    notebook: NotebookSpec,
    cells: tuple[CellSpec, ...],
    runtime: RuntimeInspection | None,
) -> dict[str, Any]:
    """Serialize selected static and runtime inspection records."""
    payload = notebook.to_dict()
    if runtime is None:
        payload["cells"] = [cell.to_dict() for cell in cells]
        return payload
    payload["cells"] = [
        {
            **cell.to_dict(),
            "runtime": runtime.runtime.cells[cell.runtime_id].to_dict(),
        }
        for cell in cells
    ]
    payload["runtime"] = runtime.runtime.values.to_dict()
    return payload


def _json_preview(value: object, *, limit: int = 160) -> str:
    rendered = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return rendered if len(rendered) <= limit else rendered[: limit - 1] + "…"


def render_inspection(
    notebook: NotebookSpec,
    cells: tuple[CellSpec, ...],
    runtime: RuntimeInspection | None,
) -> None:
    """Write selected notebook cells and runtime values in human text."""
    echo(f"{notebook.path} · {len(notebook.cells)} cells")
    for position, cell in enumerate(cells):
        if position:
            echo()
        name = cell.name or f"cell {cell.index}"
        kind = "output" if cell.has_output_expression else "compute"
        echo(
            f"{cell.index:>3}  {light_blue(f'{cell.runtime_id:<6}')} {kind:<7} "
            f"line {cell.source.start_line:<4} {name}"
        )
        echo(f"     {cell.ref}")
        if cell.definitions:
            echo(f"     defines: {', '.join(cell.definitions)}")
        if runtime is not None:
            runtime_cell = runtime.runtime.cells[cell.runtime_id]
            echo(f"     runtime: {runtime_cell.status or 'missing'}")
            outputs = ", ".join(
                (
                    f"{output.channel}:{output.mimetype}"
                    + (" (empty)" if output.empty else "")
                )
                for output in runtime_cell.outputs
            )
            echo(f"     outputs: {outputs or 'none'}")
            if runtime_cell.errors:
                echo(f"     error: {runtime_cell.errors[0]}")
    if runtime is not None:
        values = runtime.runtime.values
        echo(f"\n{light_blue('JSON values')}")
        for name, value in values.values.items():
            echo(f"  {name} = {_json_preview(value)}")
        if not values.values:
            echo("  none")
        if values.errors:
            echo(f"\n{red('Value errors')}")
            for name, error in values.errors.items():
                echo(f"  {name}: {error.code}: {error.message}")


def checks_payload(
    studio: StudioConfig,
    results: tuple[CheckResult, ...],
    *,
    view_name: str | None,
) -> dict[str, object]:
    """Serialize check results."""
    return {
        "schema": 1,
        "ok": not any(result.status == "fail" for result in results),
        "notebook": str(studio.notebook),
        "view": view_name,
        "checks": [result.to_dict() for result in results],
    }


def render_checks(results: tuple[CheckResult, ...]) -> None:
    """Write check results in human text."""
    styles = {"pass": green, "warn": yellow, "fail": red}
    for result in results:
        status = styles[result.status](f"{result.status.upper():<4}")
        echo(f"{status} {result.name}: {result.message}")
        if result.details is None:
            continue
        source = result.details.get("source")
        if isinstance(source, dict):
            path = source.get("path")
            line = source.get("line")
            column = source.get("column")
            if isinstance(path, str) and isinstance(line, int):
                location = f"{path}:{line}"
                if isinstance(column, int):
                    location += f":{column}"
                echo(f"     {location}")
        hint = result.details.get("hint")
        if isinstance(hint, str):
            echo(f"     {hint}")


def render_launch(plan: LaunchPlan) -> None:
    """Write the Studio and selected view URLs."""
    echo(f"{light_blue('Studio:')} {plan.studio_url}")
    echo(f"{light_blue('View:  ')} {plan.view_url}")
