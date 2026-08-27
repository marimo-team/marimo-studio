"""Run progressive validation for configured Studio views."""

from __future__ import annotations

import asyncio
import os
import sys
from contextlib import nullcontext
from pathlib import Path

import click

from marimo_studio._cli.diagnostics import (
    capture_runtime_stderr,
    diagnostic_format_option,
    diagnostics,
    run_in_environment,
)
from marimo_studio._cli.environment import should_reenter
from marimo_studio._cli.help import ColoredCommand
from marimo_studio._cli.options import (
    browser_client_option,
    finite_timeout,
    output_format_option,
    runtime_timeout_option,
    server_option,
    target_argument,
)
from marimo_studio._cli.output import echo_json, render_analysis, render_checks
from marimo_studio._cli.targets import load_studio_target
from marimo_studio._validation.analysis import (
    DEFAULT_BROWSER_TIMEOUT,
    MAX_BROWSER_TIMEOUT,
    AnalysisRequest,
    analyze_studio,
)
from marimo_studio._validation.records import ValidationReport
from marimo_studio._validation.runtime_process import check_runtime_studio_isolated
from marimo_studio._validation.service import validate_studio
from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio.agent._client import observe_browser_views, studio_server_connection
from marimo_studio.errors import ProtocolError

_CHECK_SEVERITY = {"pass": "info", "warn": "warning", "fail": "error"}


@click.command("validate", cls=ColoredCommand)
@target_argument
@click.option("--view", "view_name", metavar="NAME", help="Validate one named view.")
@click.option(
    "--level",
    type=click.Choice(("static", "runtime", "browser")),
    default="static",
    show_default=True,
)
@server_option()
@browser_client_option
@click.option(
    "--browser-timeout",
    type=click.FloatRange(min=0, max=MAX_BROWSER_TIMEOUT),
    callback=finite_timeout,
    default=DEFAULT_BROWSER_TIMEOUT,
    show_default=True,
)
@runtime_timeout_option
@output_format_option
@diagnostic_format_option
def validate(
    target: Path | None,
    view_name: str | None,
    level: str,
    server_url: str | None,
    browser_client: str | None,
    browser_timeout: float,
    runtime_timeout: float,
    output_format: str,
) -> None:
    """Validate saved source, runtime behavior, or the rendered browser view."""
    if browser_client is not None and server_url is None:
        raise click.BadParameter(
            "requires --server or MARIMO_STUDIO_SERVER_URL",
            param_hint="--browser-client",
        )
    if level == "browser" and server_url is None:
        raise click.BadParameter(
            "browser validation requires --server or MARIMO_STUDIO_SERVER_URL",
            param_hint="--server",
        )
    studio = load_studio_target(target)
    if level != "static" and should_reenter(studio, None):
        raise click.exceptions.Exit(run_in_environment(studio, sys.argv[1:]))
    if level == "browser":
        _validate_browser(
            studio,
            view_name,
            server_url,
            browser_client,
            browser_timeout,
            runtime_timeout,
            output_format,
        )
        return

    with capture_runtime_stderr() if level == "runtime" else nullcontext():
        run = asyncio.run(
            validate_studio(
                studio,
                level="runtime" if level == "runtime" else "static",
                view_name=view_name,
                runtime_timeout=runtime_timeout,
                runtime_checker=check_runtime_studio_isolated,
            )
        )
    static = run.static
    runtime = run.runtime
    stream = diagnostics()
    for check in (*static.checks, *runtime):
        if check.status == "pass":
            continue
        stream.emit(
            code=check.code or check.name,
            message=check.message,
            severity=_CHECK_SEVERITY[check.status],
            status=check.status,
            details=check.details,
        )
    if output_format == "json":
        echo_json(run.report.to_dict())
    else:
        render_checks((*static.checks, *runtime))
    if not static.ok or any(check.status == "fail" for check in runtime):
        raise click.exceptions.Exit(1)


def _validate_browser(
    studio: StudioWorkspace,
    view_name: str | None,
    server_url: str | None,
    browser_client: str | None,
    browser_timeout: float,
    runtime_timeout: float,
    output_format: str,
) -> None:
    try:
        assert server_url is not None
        connection = studio_server_connection(
            server_url,
            access_token=os.environ.get("MARIMO_STUDIO_ACCESS_TOKEN", ""),
            browser_client=browser_client or "",
        )
    except ProtocolError as error:
        raise click.BadParameter(str(error), param_hint="--server") from error
    request = AnalysisRequest(
        view=view_name,
        browser_timeout=browser_timeout,
        runtime_timeout=runtime_timeout,
        require_browser=True,
        browser_client=browser_client,
    )

    async def observe(
        selected: object,
        views: tuple[str, ...],
        revisions: dict[str, str],
    ):
        del selected
        return await observe_browser_views(
            connection,
            studio.notebook,
            views,
            revisions=revisions,
            runtime=studio.default_runtime,
            timeout=request.browser_timeout,
        )

    with capture_runtime_stderr():
        analysis = asyncio.run(
            analyze_studio(
                studio,
                request.options,
                observe_browser=observe,
                runtime_checker=check_runtime_studio_isolated,
            )
        )
    stream = diagnostics()
    for action in analysis.actions:
        stream.emit(
            code=action.code,
            message=action.message,
            severity=action.severity,
            status="fail" if action.severity == "error" else "warn",
            details=action.to_dict(),
        )
    if output_format == "json":
        echo_json(ValidationReport.from_analysis(analysis).to_dict())
    else:
        render_analysis(analysis)
    if not analysis.handoff_ready:
        raise click.exceptions.Exit(1)
