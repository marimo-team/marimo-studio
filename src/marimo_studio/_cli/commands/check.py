"""Validate configured Studio views."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import click

from marimo_studio._cli.diagnostics import (
    capture_runtime_stderr,
    diagnostic_format_option,
    diagnostics,
    run_in_environment,
)
from marimo_studio._cli.help import ColoredCommand
from marimo_studio._cli.options import notebook_argument, output_format_option
from marimo_studio._cli.output import (
    checks_payload,
    echo_json,
    render_checks,
)
from marimo_studio._workspace.checks import check_runtime_studio, check_studio
from marimo_studio._workspace.environment import should_reenter
from marimo_studio._workspace.targets import load_studio_target

_CHECK_SEVERITY = {"pass": "info", "warn": "warning", "fail": "error"}


@click.command("check", cls=ColoredCommand)
@notebook_argument
@click.option("--view", "view_name", help="Validate one named view.")
@click.option(
    "--runtime",
    "runtime_check",
    is_flag=True,
    help="Execute projected cells and resolve projected values.",
)
@output_format_option
@diagnostic_format_option
def check(
    notebook: Path | None,
    view_name: str | None,
    runtime_check: bool,
    output_format: str,
) -> None:
    """Validate the views configured for NOTEBOOK."""
    studio = load_studio_target(notebook)
    if runtime_check and should_reenter(studio, None):
        raise click.exceptions.Exit(run_in_environment(studio, sys.argv[1:]))
    results = check_studio(studio, view_name=view_name)
    if runtime_check and not any(result.status == "fail" for result in results):
        with capture_runtime_stderr():
            results += asyncio.run(check_runtime_studio(studio, view_name=view_name))

    stream = diagnostics()
    for result in results:
        stream.emit(
            code=result.code or result.name,
            message=result.message,
            severity=_CHECK_SEVERITY[result.status],
            status=result.status,
            details=result.details,
        )
    payload = checks_payload(studio, results, view_name=view_name)
    if output_format == "json":
        echo_json(payload)
    else:
        render_checks(results)
    if not payload["ok"]:
        raise click.exceptions.Exit(1)
