"""Validate saved source and runtime execution."""

from __future__ import annotations

import asyncio
import sys
from contextlib import nullcontext
from pathlib import Path
from typing import cast

import click

from marimo_studio._authoring.validation import validate as validate_workspace
from marimo_studio._cli.activity import activity
from marimo_studio._cli.diagnostics import (
    capture_runtime_stderr,
    diagnostics,
    json_option,
    run_in_environment,
)
from marimo_studio._cli.environment import provider_bootstrap_required, should_reenter
from marimo_studio._cli.help import ColoredCommand
from marimo_studio._cli.options import (
    runtime_timeout_option,
    target_option,
)
from marimo_studio._cli.output import echo_json, render_validation
from marimo_studio._cli.targets import (
    load_studio_target,
    resolve_environment_target,
    resolve_notebook,
)
from marimo_studio._validation.records import ValidationLevel


@click.command("validate", cls=ColoredCommand)
@click.argument("view_name", required=False, metavar="[VIEW]")
@target_option
@click.option(
    "--level",
    type=click.Choice(("static", "runtime")),
    default="static",
    show_default=True,
)
@runtime_timeout_option
@json_option
def validate(
    view_name: str | None,
    target: Path | None,
    level: str,
    runtime_timeout: float,
    json_output: bool,
) -> None:
    """Validate every configured view or one selected view.

    When needed, Studio reruns the command through uv with requirements derived
    from the target's saved views and Python metadata. uv may resolve and install
    packages before provider code loads. Reviewed provider code then runs with
    the current user's filesystem, environment, and network authority.
    """
    notebook = resolve_notebook(target)
    environment = resolve_environment_target(target, notebook)
    if provider_bootstrap_required(environment):
        raise click.exceptions.Exit(run_in_environment(environment, sys.argv[1:]))
    studio = load_studio_target(target)
    if level != "static" and should_reenter(studio, None):
        raise click.exceptions.Exit(run_in_environment(studio, sys.argv[1:]))
    with (
        activity(diagnostics(), phase=f"validate:{level}", view=view_name),
        capture_runtime_stderr() if level != "static" else nullcontext(),
    ):
        report = asyncio.run(
            validate_workspace(
                studio.notebook,
                level=cast(ValidationLevel, level),
                view=view_name,
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
