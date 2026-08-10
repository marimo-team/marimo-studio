"""Run the complete agent handoff gate."""

from __future__ import annotations

import asyncio
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
from marimo_studio._cli.options import output_format_option, target_argument
from marimo_studio._cli.output import echo_json, render_analysis
from marimo_studio._workspace.environment import should_reenter
from marimo_studio._workspace.targets import load_studio_target
from marimo_studio.analysis import analyze_studio


@click.command("analyze", cls=ColoredCommand)
@target_argument
@click.option("--view", "view_name", help="Analyze one named view.")
@click.option(
    "--server",
    "server_url",
    envvar="MARIMO_STUDIO_SERVER_URL",
    help="Read rendered readiness from a running Studio server URL.",
)
@click.option(
    "--access-token",
    envvar="MARIMO_STUDIO_ACCESS_TOKEN",
    help="Authenticate to the running server. Prefer the environment variable.",
)
@click.option(
    "--browser-timeout",
    type=click.FloatRange(min=0),
    default=10.0,
    show_default=True,
    help="Seconds to wait for current rendered-view evidence.",
)
@output_format_option
@diagnostic_format_option
def analyze(
    target: Path | None,
    view_name: str | None,
    server_url: str | None,
    access_token: str | None,
    browser_timeout: float,
    output_format: str,
) -> None:
    """Analyze configured views and report whether they are ready to hand off.

    TARGET may be a notebook, project directory, or pyproject.toml. The current
    directory is used when TARGET is omitted.
    """
    studio = load_studio_target(target)
    if should_reenter(studio, None):
        raise click.exceptions.Exit(run_in_environment(studio, sys.argv[1:]))

    connection = (
        studio_server_connection(server_url, access_token=access_token or "")
        if server_url is not None
        else None
    )

    async def observe(
        _studio: object,
        views: tuple[str, ...],
    ):
        assert connection is not None
        return await observe_browser_views(
            connection,
            studio.notebook,
            views,
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
