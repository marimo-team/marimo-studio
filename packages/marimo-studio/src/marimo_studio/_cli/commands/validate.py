"""Validate saved source, runtime execution, and rendered browser evidence."""

from __future__ import annotations

import asyncio
import os
import sys
from contextlib import nullcontext
from pathlib import Path
from typing import cast

import click

from marimo_studio._authoring.validation import validate as validate_workspace
from marimo_studio._browser_client.transport import studio_server_connection
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
    target_option,
)
from marimo_studio._cli.output import echo_json, render_validation
from marimo_studio._cli.targets import load_studio_target
from marimo_studio._validation.limits import (
    DEFAULT_BROWSER_TIMEOUT,
    MAX_BROWSER_TIMEOUT,
)
from marimo_studio._validation.records import ValidationLevel
from marimo_studio.errors import ProtocolError


@click.command("validate", cls=ColoredCommand)
@click.argument("view_name", required=False, metavar="[VIEW]")
@target_option
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
    view_name: str | None,
    target: Path | None,
    level: str,
    server_url: str | None,
    browser_client: str | None,
    browser_timeout: float,
    runtime_timeout: float,
    output_format: str,
) -> None:
    """Validate every configured view or one selected view."""
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
    connection = None
    if server_url is not None:
        try:
            connection = studio_server_connection(
                server_url,
                access_token=os.environ.get("MARIMO_STUDIO_ACCESS_TOKEN", ""),
                browser_client=browser_client or "",
            )
        except ProtocolError as error:
            raise click.BadParameter(str(error), param_hint="--server") from error
    with capture_runtime_stderr() if level != "static" else nullcontext():
        report = asyncio.run(
            validate_workspace(
                studio.notebook,
                level=cast(ValidationLevel, level),
                view=view_name,
                connection=connection,
                browser_timeout=browser_timeout,
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
            details=action.to_dict(),
        )
    if output_format == "json":
        echo_json(report.to_dict())
    else:
        render_validation(report)
    if report.level == "browser":
        if not report.handoff_ready:
            raise click.exceptions.Exit(1)
    elif not report.ok:
        raise click.exceptions.Exit(1)
