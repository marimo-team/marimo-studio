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
    diagnostics,
    json_option,
    run_in_environment,
)
from marimo_studio._cli.environment import provider_bootstrap_required, should_reenter
from marimo_studio._cli.help import ColoredCommand
from marimo_studio._cli.options import (
    browser_client_option,
    finite_timeout,
    runtime_timeout_option,
    server_option,
    target_option,
)
from marimo_studio._cli.output import echo_json, render_validation
from marimo_studio._cli.targets import (
    load_studio_target,
    resolve_environment_target,
    resolve_notebook,
)
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
@json_option
def validate(
    view_name: str | None,
    target: Path | None,
    level: str,
    server_url: str | None,
    browser_client: str | None,
    browser_timeout: float,
    runtime_timeout: float,
    json_output: bool,
) -> None:
    """Validate every configured view or one selected view.

    When needed, Studio reruns the command through uv with requirements derived
    from the target's saved views and Python metadata. uv may resolve and install
    packages before provider code loads. Reviewed provider code then runs with
    the current user's filesystem, environment, and network authority.
    """
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
    if level == "browser" and view_name is None:
        raise click.BadParameter(
            "browser validation requires a named view",
            param_hint="VIEW",
        )
    notebook = resolve_notebook(target)
    environment = resolve_environment_target(target, notebook)
    if provider_bootstrap_required(environment):
        raise click.exceptions.Exit(run_in_environment(environment, sys.argv[1:]))
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
    for issue in report.issues:
        stream.emit(
            code=issue.code,
            message=issue.message,
            severity=issue.severity,
            status="fail" if issue.severity == "error" else "warn",
            details=issue.to_dict(),
        )
    if json_output:
        echo_json(report.to_dict())
    else:
        render_validation(report)
    if not report.ok:
        raise click.exceptions.Exit(1)
