"""Create and remove named Studio views."""

from __future__ import annotations

import asyncio
from pathlib import Path

import click

from marimo_studio._authoring.view import remove_view
from marimo_studio._authoring.workspace import create_view
from marimo_studio._cli.diagnostics import json_option
from marimo_studio._cli.help import ColoredCommand
from marimo_studio._cli.options import (
    target_option,
    view_name_argument,
)
from marimo_studio._cli.output import (
    echo_json,
    render_view_next_command,
    render_view_removal,
    render_view_setup,
)
from marimo_studio._cli.targets import resolve_notebook


def _stdin_is_interactive() -> bool:
    return click.get_text_stream("stdin").isatty()


@click.command("create", cls=ColoredCommand)
@view_name_argument
@target_option
@click.option(
    "--starter",
    default=None,
    metavar="ID",
    help="Choose an installed starting point for the page.",
)
@click.option("--dry-run", is_flag=True, help="Report changes without writing.")
@json_option
def create(
    view_name: str,
    target: Path | None,
    starter: str | None,
    dry_run: bool,
    json_output: bool,
) -> None:
    """Create one named page."""
    result = asyncio.run(
        create_view(
            resolve_notebook(target),
            view_name,
            starter=starter,
            dry_run=dry_run,
        )
    )
    if json_output:
        echo_json(result.to_dict())
        render_view_next_command(result)
        return
    render_view_setup(result)


@click.command("remove", cls=ColoredCommand)
@view_name_argument
@target_option
@click.option("--yes", is_flag=True, help="Remove the page without prompting.")
@json_option
def remove(
    view_name: str,
    target: Path | None,
    yes: bool,
    json_output: bool,
) -> None:
    """Remove one page and its source files."""
    if not yes and (json_output or not _stdin_is_interactive()):
        raise click.UsageError(
            "Pass --yes for machine output or non-interactive input."
        )
    if not yes and not click.confirm(
        f"Remove view {view_name!r} and its project directory?",
        default=False,
        err=True,
    ):
        raise click.exceptions.Exit(0)
    result = asyncio.run(remove_view(resolve_notebook(target), view_name))
    if json_output:
        echo_json(result.to_dict())
        return
    render_view_removal(result)
