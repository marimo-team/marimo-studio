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
from marimo_studio._cli.options import (
    output_format_option,
    runtime_timeout_option,
    target_argument,
)
from marimo_studio._cli.output import (
    echo_json,
    render_checks,
)
from marimo_studio._runtime_process import check_runtime_studio_isolated
from marimo_studio._workspace.environment import should_reenter
from marimo_studio._workspace.targets import load_studio_target
from marimo_studio.checks import check_studio

_CHECK_SEVERITY = {"pass": "info", "warn": "warning", "fail": "error"}


@click.command("check", cls=ColoredCommand)
@target_argument
@click.option("--view", "view_name", help="Validate one named view.")
@click.option(
    "--runtime",
    "runtime_check",
    is_flag=True,
    help="Execute projected cells and resolve projected values.",
)
@runtime_timeout_option
@output_format_option
@diagnostic_format_option
def check(
    target: Path | None,
    view_name: str | None,
    runtime_check: bool,
    runtime_timeout: float,
    output_format: str,
) -> None:
    """Validate the views configured for TARGET.

    TARGET may be a notebook, project directory, or pyproject.toml. The current
    directory is used when TARGET is omitted.
    """
    studio = load_studio_target(target)
    if runtime_check and should_reenter(studio, None):
        raise click.exceptions.Exit(run_in_environment(studio, sys.argv[1:]))
    report = check_studio(studio, view_name=view_name)
    if runtime_check and report.ok:
        with capture_runtime_stderr():
            report = report.extend(
                asyncio.run(
                    check_runtime_studio_isolated(
                        studio,
                        view_name=view_name,
                        timeout=runtime_timeout,
                    )
                )
            )

    stream = diagnostics()
    for result in report.checks:
        stream.emit(
            code=result.code or result.name,
            message=result.message,
            severity=_CHECK_SEVERITY[result.status],
            status=result.status,
            details=result.details,
        )
    if output_format == "json":
        echo_json(report.to_dict())
    else:
        render_checks(report.checks)
    if not report.ok:
        raise click.exceptions.Exit(1)
