"""Inspect notebook cells through static and runtime services."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import click

from marimo_studio._cli.diagnostics import (
    capture_runtime_stderr,
    diagnostic_format_option,
    run_in_environment,
)
from marimo_studio._cli.help import ColoredCommand
from marimo_studio._cli.options import (
    output_format_option,
    runtime_timeout_option,
    target_argument,
)
from marimo_studio._cli.output import echo_json, render_inspection
from marimo_studio._workspace.environment import should_reenter
from marimo_studio._workspace.targets import (
    resolve_environment_target,
    resolve_notebook,
)
from marimo_studio.errors import ConfigurationError
from marimo_studio.inspect import inspect_notebook_result, inspect_runtime


@click.command("inspect", cls=ColoredCommand)
@target_argument
@click.option("--include-code", is_flag=True, help="Include complete cell source.")
@click.option(
    "--display",
    "output_expressions",
    is_flag=True,
    help="Return cells with a final output expression.",
)
@click.option(
    "--runtime",
    is_flag=True,
    help="Execute cells and include MIME outputs and JSON values.",
)
@click.option("--limit", type=click.IntRange(min=1), help="Limit cell records.")
@runtime_timeout_option
@output_format_option
@diagnostic_format_option
def inspect(
    target: Path | None,
    include_code: bool,
    output_expressions: bool,
    runtime: bool,
    limit: int | None,
    runtime_timeout: float,
    output_format: str,
) -> None:
    """Inspect cells in TARGET.

    TARGET may be a notebook, project directory, or pyproject.toml. The current
    directory is used when TARGET is omitted.
    """
    notebook_path = resolve_notebook(target)
    if not notebook_path.is_file():
        raise ConfigurationError(f"Notebook does not exist: {notebook_path}")

    if runtime:
        environment = resolve_environment_target(target, notebook_path)
        if should_reenter(environment, None):
            raise click.exceptions.Exit(run_in_environment(environment, sys.argv[1:]))
        with capture_runtime_stderr():
            result = asyncio.run(
                inspect_runtime(
                    notebook_path,
                    include_code=include_code,
                    runtime_timeout=runtime_timeout,
                )
            )
        result = result.select(
            output_expressions=output_expressions,
            limit=limit,
        )
    else:
        result = inspect_notebook_result(
            notebook_path,
            include_code=include_code,
            output_expressions=output_expressions,
            limit=limit,
        )

    if output_format == "json":
        echo_json(result.to_dict())
    else:
        render_inspection(result)
