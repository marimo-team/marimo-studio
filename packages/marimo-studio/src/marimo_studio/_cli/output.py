"""Render CLI results as human text or stable JSON."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from datetime import datetime, timezone
from typing import Any

from marimo_studio._browser_client.records import ShowResult
from marimo_studio._cli.diagnostics import diagnostics
from marimo_studio._cli.print import echo, green, light_blue, red, yellow
from marimo_studio._delivery.export import StaticExportResult
from marimo_studio._delivery.preflight import StaticPreflightReport
from marimo_studio._notebook.inspection import InspectionResult
from marimo_studio._validation.records import ValidationReport
from marimo_studio._views.api import ViewRemovalResult
from marimo_studio._views.overview import StudioOverview
from marimo_studio._views.records import ViewDocument, ViewInspection, ViewSetupResult
from marimo_studio._workspace.models import BindingResult


def _shell_command(arguments: list[str]) -> str:
    if os.name == "nt":
        return subprocess.list2cmdline(arguments)
    return shlex.join(arguments)


def _uvx_command(
    requirements: tuple[str, ...],
    arguments: list[str],
    *,
    executable_requirement: str | None = None,
) -> str:
    command = ["uvx"]
    if executable_requirement is not None:
        command.extend(["--from", executable_requirement])
    for requirement in requirements:
        if requirement == executable_requirement:
            continue
        command.extend(["--with", requirement])
    command.extend(arguments)
    return _shell_command(command)


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
    render_view_next_command(result)


def render_view_next_command(result: ViewSetupResult) -> None:
    """Show the next command after a completed view creation."""
    if result.dry_run:
        return
    command = _uvx_command(
        result.launch_requirements,
        [
            "marimo",
            "edit",
            str(result.notebook),
            "--sandbox",
        ],
    )
    _echo_next_command("edit", command)


def render_view_inspection(result: ViewInspection) -> None:
    """Write view authoring state in human text."""
    echo(result.view)
    echo(f"  {light_blue('provider')} {result.provider or 'unavailable'}")
    echo(f"  {light_blue('root')} {result.root}")
    echo(f"  {light_blue('source')} {result.project_revision or 'incomplete'}")
    echo(f"  build {result.freshness}")
    hold = result.publication_hold
    if hold is not None:
        expires = datetime.fromtimestamp(hold.expires_at, timezone.utc).isoformat()
        echo(f"  publication {hold.status} · {hold.owner} · expires {expires}")
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
        if diagnostic.hint:
            echo(f"      {light_blue('repair')} {diagnostic.hint}")
    if not result.diagnostics:
        echo("    none")
    if result.build is not None:
        echo(
            f"  {light_blue('published')} {result.build.profile} "
            f"{result.build.revision}"
        )
        echo(f"    source {result.published_project_revision}")
    echo(f"  {light_blue('latest attempt')} {result.latest_build.phase}")
    for diagnostic in result.latest_build.diagnostics:
        echo(f"    {diagnostic.severity} {diagnostic.code}: {diagnostic.message}")
        if diagnostic.hint:
            echo(f"      {light_blue('repair')} {diagnostic.hint}")


def render_status(result: StudioOverview) -> None:
    """Write Studio workspace state in human text."""
    echo(f"{result.notebook} · {result.state}")
    if result.config_path is not None:
        source = f" {result.config_source}" if result.config_source is not None else ""
        echo(f"  {light_blue('config')}{source} {result.config_path}")
    if result.default_runtime is not None:
        echo(f"  {light_blue('runtime')} {result.default_runtime}")
    if result.runtimes:
        echo(f"  {light_blue('runtimes')} {', '.join(result.runtimes)}")
    if result.bindings:
        echo(f"  {light_blue('aliases')}")
        for alias, ref in sorted(result.bindings.items()):
            echo(f"    {alias} {ref}")
    for view in result.views:
        suffix = " (default)" if view.default else ""
        echo(f"  {light_blue(view.name)}{suffix}\n    {view.path}")
    if result.state == "unconfigured":
        command = _uvx_command(
            result.launch_requirements,
            [
                "marimo-studio",
                "view",
                "create",
                "dashboard",
                "--target",
                str(result.notebook),
            ],
            executable_requirement=result.launch_requirements[0],
        )
        _echo_next_command("create", command)
    elif result.state == "needs-view" and result.default_view is not None:
        command = _uvx_command(
            result.launch_requirements,
            [
                "marimo-studio",
                "view",
                "create",
                result.default_view,
                "--target",
                str(result.notebook),
            ],
            executable_requirement=result.launch_requirements[0],
        )
        _echo_next_command("create", command)


def render_view_document(document: ViewDocument) -> None:
    """Write one revision-bound source document."""
    echo(f"{document.path.as_posix()} · {document.revision}")
    echo(document.content)


def render_document_write(document: ViewDocument) -> None:
    """Write a completed source mutation."""
    echo(f"{green('Updated')} {document.path.as_posix()}")
    echo(f"  {light_blue('revision')} {document.revision}")


def render_view_removal(result: ViewRemovalResult) -> None:
    """Write a completed view removal in human text."""
    echo(f"{green('Removed')} view {result.view} from {result.notebook}")
    echo(f"  {light_blue('default')} {result.default_view}")


def render_view_show(result: ShowResult) -> None:
    """Write a completed browser view selection in human text."""
    echo(f"{green('Showing')} view {result.view} in {result.client_id}")
    echo(f"  {light_blue('session')} {result.session_id}")


def render_static_export(result: StaticExportResult) -> None:
    """Write a static export result in human text."""
    echo(f"{green('Exported')} {result.view} with {result.runtime} to {result.output}")
    if result.cache_activity is not None:
        activity = result.cache_activity
        echo(
            f"  {light_blue('marimo cache')} "
            f"{activity.authored_hits} authored hits, "
            f"{activity.authored_misses} authored misses"
        )
    preflight = result.preflight
    echo(
        f"  {light_blue('preflight')} "
        f"{preflight.inspected_files}/{preflight.browser_files} browser sources, "
        f"{preflight.references} references, "
        f"{len(preflight.projections)} projections"
    )
    for issue in preflight.issues:
        echo(f"    {issue.severity} {issue.code}: {issue.message}")
    for warning in result.warnings:
        echo(f"  {yellow('warning')} {warning.code}: {warning.message}")
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


def render_static_preflight(result: StaticPreflightReport) -> None:
    """Write one completed static delivery preflight."""
    echo(f"{green('Verified')} {result.view} with {result.runtime}")
    echo(f"  {light_blue('files')} {result.files}")
    echo(
        f"  {light_blue('browser sources')} "
        f"{result.inspected_files}/{result.browser_files}"
    )
    echo(f"  {light_blue('references')} {result.references}")
    if result.projections:
        echo(f"  {light_blue('projections')}")
        for projection in result.projections:
            target = projection.target or "dynamic target"
            echo(f"    {projection.status:<21} {projection.projection} {target}")
    if result.issues:
        echo(f"  {light_blue('diagnostics')}")
        for issue in result.issues:
            echo(
                f"    {issue.severity} {issue.code}: {issue.message} "
                f"({issue.source.path}:{issue.source.line}:{issue.source.column})"
            )


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
        echo(f"\n{light_blue('Values')}")
        for name, value in values.values.items():
            echo(f"  {name} = {_json_preview(value)}")
        if not values.values:
            echo("  none")
        if values.errors:
            echo(f"\n{red('Value errors')}")
            for name, error in values.errors.items():
                echo(f"  {name}: {error.code}: {error.message}")


def _render_check(record: object) -> None:
    if not isinstance(record, dict):
        return
    status = record.get("status")
    name = record.get("name")
    message = record.get("message")
    if status not in {"pass", "warn", "fail"}:
        return
    if not isinstance(name, str) or not isinstance(message, str):
        return
    styles = {"pass": green, "warn": yellow, "fail": red}
    echo(f"{styles[status](f'{status.upper():<4}')} {name}: {message}")
    details = record.get("details")
    if isinstance(details, dict):
        source = details.get("source")
        if isinstance(source, dict):
            path = source.get("path")
            line = source.get("line")
            column = source.get("column")
            if isinstance(path, str) and isinstance(line, int):
                location = f"{path}:{line}"
                if isinstance(column, int):
                    location += f":{column}"
                echo(f"     {location}")
        hint = details.get("hint")
        if isinstance(hint, str):
            echo(f"     {hint}")


def render_validation(report: ValidationReport) -> None:
    """Write progressive validation evidence in human text."""
    state = green("READY") if report.ok else red("NEEDS REPAIR")
    echo(f"{state} {report.notebook}")
    echo(f"  {light_blue('level')} {report.level}")
    if report.view is not None:
        echo(f"  {light_blue('view')} {report.view}")
    for stage in ("static", "runtime"):
        evidence = report.evidence.get(stage)
        if not isinstance(evidence, dict):
            continue
        checks = evidence.get("checks")
        if isinstance(checks, list):
            for check in checks:
                _render_check(check)
    browser = report.evidence.get("browser")
    if isinstance(browser, dict):
        observations = browser.get("observations")
        if isinstance(observations, list):
            for observation in observations:
                if not isinstance(observation, dict):
                    continue
                state_name = observation.get("state")
                view = observation.get("view")
                if not isinstance(state_name, str) or not isinstance(view, str):
                    continue
                style = green if state_name == "ready" else red
                echo(f"{style(state_name.upper()):<4} browser:{view}")
                message = observation.get("message")
                if isinstance(message, str) and message:
                    echo(f"     {message}")
    if report.issues:
        echo(f"\n{light_blue('Repair queue')}")
        for issue in report.issues:
            target = f" [{issue.view}]" if issue.view else ""
            echo(f"  {issue.severity.upper()} {issue.code}{target}: {issue.advice}")
