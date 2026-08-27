"""Create and remove named Studio views."""

from __future__ import annotations

import asyncio
from pathlib import Path

import click

from marimo_studio._authoring.view import remove_view
from marimo_studio._authoring.workspace import create_view
from marimo_studio._cli.diagnostics import diagnostic_format_option, diagnostics
from marimo_studio._cli.help import ColoredCommand
from marimo_studio._cli.options import (
    output_format_option,
    target_option,
    view_name_argument,
)
from marimo_studio._cli.output import (
    echo_json,
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
    help="Create the view from an installed starter.",
)
@click.option("--dry-run", is_flag=True, help="Report changes without writing.")
@output_format_option
@diagnostic_format_option
def create(
    view_name: str,
    target: Path | None,
    starter: str | None,
    dry_run: bool,
    output_format: str,
) -> None:
    """Create one named view."""
    result = asyncio.run(
        create_view(
            resolve_notebook(target),
            view_name,
            starter=starter,
            dry_run=dry_run,
        )
    )
    if output_format == "json":
        echo_json(result.to_dict())
        return
    render_view_setup(result)


@click.command("remove", cls=ColoredCommand)
@view_name_argument
@target_option
@click.option("--yes", is_flag=True, help="Remove the view without prompting.")
@output_format_option
@diagnostic_format_option
def remove(
    view_name: str,
    target: Path | None,
    yes: bool,
    output_format: str,
) -> None:
    """Remove one complete view project."""
    if not yes and (
        output_format == "json"
        or diagnostics().format == "jsonl"
        or not _stdin_is_interactive()
    ):
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
    if output_format == "json":
        echo_json(result.to_dict())
        return
    render_view_removal(result)
