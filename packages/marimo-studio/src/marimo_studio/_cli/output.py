"""Render CLI results as human text or stable JSON."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from typing import Any

from marimo_studio._cli.diagnostics import diagnostics
from marimo_studio._cli.print import echo, green, light_blue, red, yellow
from marimo_studio._delivery.export import StaticExportResult
from marimo_studio._notebook.inspection import InspectionResult
from marimo_studio._validation.analysis import AnalysisReport
from marimo_studio._validation.results import CheckResult
from marimo_studio._views.api import ViewRemovalResult
from marimo_studio._views.overview import StudioOverview
from marimo_studio._views.records import ViewInspection, ViewSetupResult
from marimo_studio._workspace.models import BindingResult
from marimo_studio.agent._records import ViewActivationResult


def _shell_command(arguments: list[str]) -> str:
    if os.name == "nt":
        return subprocess.list2cmdline(arguments)
    return shlex.join(arguments)


def echo_error(message: str) -> None:
    """Write a human error to stderr."""
    echo(red(message), err=True)


def echo_json(value: Any) -> None:
    """Write a deterministic JSON result to stdout."""
    diagnostics().write_result(json.dumps(value, indent=2, sort_keys=True))


def _echo_next_command(action: str, command: str) -> None:
    if diagnostics().emit(
        code="next-command",
        message=command,
        severity="info",
        details={"action": action},
    ):
        return
    echo(f"  {light_blue(action)} {command}", err=True)


def render_view_setup(result: ViewSetupResult) -> None:
    """Write a view setup result in human text."""
    verb = "Would create" if result.dry_run else "Created"
    echo(f"{green(verb)} view {result.name} at {result.root}")
    for path in result.created:
        echo(f"  {light_blue('create')} {path}")
    for path in result.updated:
        echo(f"  {light_blue('update')} {path}")
    if not result.dry_run:
        command = _shell_command(["marimo", "edit", str(result.notebook), "--sandbox"])
        _echo_next_command("edit", command)


def render_view_inspection(result: ViewInspection) -> None:
    """Write view authoring state in human text."""
    echo(result.view)
    echo(f"  {light_blue('provider')} {result.provider}")
    echo(f"  build {result.freshness}")
    echo(f"  {light_blue('documents')}")
    for document in result.documents:
        echo(
            f"    {document.access:<4} {document.language:<18} "
            f"{document.path.as_posix()}"
        )
    echo(f"  {light_blue('diagnostics')}")
    for diagnostic in result.diagnostics:
        source = (
            f" · {diagnostic.path}:{diagnostic.line}:{diagnostic.column}"
            if diagnostic.path is not None
            else ""
        )
        echo(
            f"    {diagnostic.severity} {diagnostic.code}: {diagnostic.message}{source}"
        )
    if not result.diagnostics:
        echo("    none")


def render_overview(result: StudioOverview) -> None:
    """Write Studio workspace state in human text."""
    echo(f"{result.notebook} · {result.state}")
    if result.config_path is not None:
        echo(f"  {light_blue('config')} {result.config_path}")
    if result.default_runtime is not None:
        echo(f"  {light_blue('runtime')} {result.default_runtime}")
    for view in result.views:
        suffix = " (default)" if view.default else ""
        echo(f"  {light_blue(view.name)}{suffix}\n    {view.path}")
    if result.state == "unconfigured":
        command = _shell_command(
            ["marimo-studio", "view", "create", str(result.notebook)]
        )
        _echo_next_command("create", command)
    elif result.state == "needs-view" and result.default_view is not None:
        command = _shell_command(
            [
                "marimo-studio",
                "view",
                "create",
                str(result.notebook),
                "--name",
                result.default_view,
            ]
        )
        _echo_next_command("create", command)


def render_view_removal(result: ViewRemovalResult) -> None:
    """Write a completed view removal in human text."""
    echo(f"{green('Removed')} view {result.view} from {result.notebook}")
    echo(f"  {light_blue('default')} {result.default_view}")


def render_view_activation(result: ViewActivationResult) -> None:
    """Write a completed browser view activation in human text."""
    echo(f"{green('Activated')} view {result.view} in {result.client_id}")
    echo(f"  {light_blue('session')} {result.session_id}")


def render_static_export(result: StaticExportResult) -> None:
    """Write a static export result in human text."""
    echo(f"{green('Exported')} {result.view} to {result.output}")
    echo(f"  {light_blue('open')} {result.entrypoint}")
    command = _shell_command(
        [
            "python",
            "-m",
            "http.server",
            "--bind",
            "127.0.0.1",
            "--directory",
            str(result.output),
        ]
    )
    echo(f"  {light_blue('serve')} {command}")


def render_binding(result: BindingResult) -> None:
    """Write a cell binding result in human text."""
    if result.previous_ref == result.cell.ref:
        echo(f"{result.alias} already points to cell {result.cell.index}")
        return
    verb = "Would bind" if result.dry_run else "Bound"
    echo(
        f"{green(verb)} {result.alias} to cell {result.cell.index} "
        f"({result.cell.source.start_line}-{result.cell.source.end_line})"
    )


def _json_preview(value: object, *, limit: int = 160) -> str:
    rendered = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return rendered if len(rendered) <= limit else rendered[: limit - 1] + "…"


def render_inspection(result: InspectionResult) -> None:
    """Write selected notebook cells and runtime values in human text."""
    notebook = result.notebook
    cells = result.cells
    runtime = result.runtime
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
            runtime_cell = runtime.cells[cell.runtime_id]
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
        values = runtime.values
        echo(f"\n{light_blue('JSON values')}")
        for name, value in values.values.items():
            echo(f"  {name} = {_json_preview(value)}")
        if not values.values:
            echo("  none")
        if values.errors:
            echo(f"\n{red('Value errors')}")
            for name, error in values.errors.items():
                echo(f"  {name}: {error.code}: {error.message}")


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


def render_analysis(report: AnalysisReport) -> None:
    """Write an agent analysis report in human text."""
    state = green("HANDOFF READY") if report.handoff_ready else red("NEEDS REPAIR")
    echo(f"{state} {report.notebook}")
    echo(f"  {light_blue('views')} {', '.join(report.views)}")
    render_checks(report.static_checks)
    if report.runtime_skipped is not None:
        echo(f"{yellow('SKIP')} runtime: {report.runtime_skipped}")
    else:
        render_checks(report.runtime_checks)
    for observation in report.browser_observations:
        style = green if observation.state == "ready" else red
        echo(f"{style(observation.state.upper()):<4} browser:{observation.view}")
        if observation.message:
            echo(f"     {observation.message}")
    if report.actions:
        echo(f"\n{light_blue('Repair queue')}")
        for action in report.actions:
            target = f" [{action.view}]" if action.view else ""
            echo(f"  {action.severity.upper()} {action.code}{target}: {action.advice}")
