"""Run the complete agent handoff gate."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import click

from marimo_studio._agent_client import (
    observe_browser_views,
    studio_server_connection,
)
from marimo_studio._cli.diagnostics import (
    capture_runtime_stderr,
    diagnostic_format_option,
    diagnostics,
    run_in_environment,
)
from marimo_studio._cli.help import ColoredCommand
from marimo_studio._cli.options import (
    finite_timeout,
    output_format_option,
    runtime_timeout_option,
    target_argument,
)
from marimo_studio._cli.output import echo_json, render_analysis
from marimo_studio._runtime_process import check_runtime_studio_isolated
from marimo_studio._workspace.environment import should_reenter
from marimo_studio._workspace.targets import load_studio_target
from marimo_studio.analysis import analyze_studio
from marimo_studio.errors import ProtocolError

_MAX_BROWSER_TIMEOUT = 300.0


@click.command("analyze", cls=ColoredCommand)
@target_argument
@click.option("--view", "view_name", help="Analyze one named view.")
@click.option(
    "--server",
    "server_url",
    envvar="MARIMO_STUDIO_SERVER_URL",
    help=(
        "Read rendered readiness from a running Studio server URL. Set "
        "MARIMO_STUDIO_ACCESS_TOKEN when the server requires authentication."
    ),
)
@click.option(
    "--browser-client",
    envvar="MARIMO_STUDIO_BROWSER_CLIENT",
    help="Target one connected Studio browser client.",
)
@click.option(
    "--browser-timeout",
    type=click.FloatRange(min=0, max=_MAX_BROWSER_TIMEOUT),
    callback=finite_timeout,
    default=10.0,
    show_default=True,
    help="Seconds to wait for current rendered-view evidence.",
)
@runtime_timeout_option
@output_format_option
@diagnostic_format_option
def analyze(
    target: Path | None,
    view_name: str | None,
    server_url: str | None,
    browser_client: str | None,
    browser_timeout: float,
    runtime_timeout: float,
    output_format: str,
) -> None:
    """Analyze configured views and report whether they are ready to hand off.

    TARGET may be a notebook, project directory, or pyproject.toml. The current
    directory is used when TARGET is omitted.
    """
    if browser_client is not None and server_url is None:
        raise click.BadParameter(
            "requires --server or MARIMO_STUDIO_SERVER_URL",
            param_hint="--browser-client",
        )

    studio = load_studio_target(target)
    if should_reenter(studio, None):
        raise click.exceptions.Exit(run_in_environment(studio, sys.argv[1:]))

    try:
        connection = (
            studio_server_connection(
                server_url,
                access_token=os.environ.get("MARIMO_STUDIO_ACCESS_TOKEN", ""),
                browser_client=browser_client or "",
            )
            if server_url is not None
            else None
        )
    except ProtocolError as error:
        raise click.BadParameter(str(error), param_hint="--server") from error

    async def observe(
        _studio: object,
        views: tuple[str, ...],
        revisions: dict[str, str],
    ):
        assert connection is not None
        return await observe_browser_views(
            connection,
            studio.notebook,
            views,
            revisions=revisions,
            runtime=studio.default_runtime,
            timeout=browser_timeout,
        )

    with capture_runtime_stderr():
        report = asyncio.run(
            analyze_studio(
                studio,
                view_name=view_name,
                observe_browser=observe if connection is not None else None,
                require_browser=True,
                runtime_checker=check_runtime_studio_isolated,
                runtime_timeout=runtime_timeout,
            )
        )

    stream = diagnostics()
    for action in report.actions:
        stream.emit(
            code=action.code,
            message=action.message,
            severity=action.severity,
            status="fail" if action.severity == "error" else "warn",
            details={
                "stage": action.stage,
                "advice": action.advice,
                **({"view": action.view} if action.view is not None else {}),
                **({"target": action.target} if action.target is not None else {}),
                **({"source": action.source} if action.source is not None else {}),
            },
        )
    if output_format == "json":
        echo_json(report.to_dict())
    else:
        render_analysis(report)
    if not report.handoff_ready:
        raise click.exceptions.Exit(1)


__all__ = ["analyze"]
