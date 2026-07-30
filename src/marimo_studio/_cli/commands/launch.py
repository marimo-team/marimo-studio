"""Launch Studio through Marimo's native edit command."""

from __future__ import annotations

from pathlib import Path

import click

from marimo_studio._cli.help import LAUNCH_COMMAND, LaunchCommand
from marimo_studio._cli.options import notebook_argument
from marimo_studio._cli.output import render_launch
from marimo_studio._workspace.launch import (
    LaunchArgumentError,
    LaunchRequest,
    execute_launch,
    prepare_launch,
    validate_base_url,
)
from marimo_studio._workspace.targets import resolve_notebook


def _base_url(
    _context: click.Context,
    parameter: click.Parameter,
    value: str,
) -> str:
    try:
        return validate_base_url(value)
    except LaunchArgumentError as error:
        raise click.BadParameter(str(error), param=parameter) from error


@click.command(
    LAUNCH_COMMAND,
    cls=LaunchCommand,
    hidden=True,
    context_settings={"ignore_unknown_options": False},
)
@notebook_argument
@click.argument("marimo_args", nargs=-1, type=click.UNPROCESSED)
@click.option("--view", "view_name", help="Open a named view.")
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=8000, show_default=True, type=click.IntRange(1, 65535))
@click.option("--open/--headless", "open_browser", default=True, show_default=True)
@click.option(
    "--base-url",
    default="",
    callback=_base_url,
    help="Serve beneath this URL path.",
)
def launch(
    notebook: Path | None,
    marimo_args: tuple[str, ...],
    view_name: str | None,
    host: str,
    port: int,
    open_browser: bool,
    base_url: str,
) -> None:
    """Configure NOTEBOOK and open Studio."""
    request = LaunchRequest(
        notebook=resolve_notebook(notebook),
        view_name=view_name,
        host=host,
        port=port,
        open_browser=open_browser,
        base_url=base_url,
        marimo_args=marimo_args,
    )
    try:
        plan = prepare_launch(request)
    except LaunchArgumentError as error:
        raise click.UsageError(str(error)) from error
    render_launch(plan)
    raise click.exceptions.Exit(execute_launch(plan))
