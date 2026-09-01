"""Create and remove named Studio views."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import click

from marimo_studio._authoring.view import remove_view
from marimo_studio._authoring.workspace import create_view
from marimo_studio._cli.diagnostics import json_option, run_in_environment
from marimo_studio._cli.environment import provider_bootstrap_required
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
from marimo_studio._cli.targets import resolve_environment_target, resolve_notebook


def _stdin_is_interactive() -> bool:
    return click.get_text_stream("stdin").isatty()


@click.command("create", cls=ColoredCommand)
@view_name_argument
@target_option
@click.option(
    "--starter",
    default=None,
    metavar="ID",
    help="Choose an installed starting point for the view.",
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
    """Create one named view.

    When needed, Studio reruns the command through uv with requirements derived
    from the target's saved views and Python metadata. uv may resolve and install
    packages before provider code loads. Reviewed provider code then runs with
    the current user's filesystem, environment, and network authority.
    """
    notebook = resolve_notebook(target)
    environment = resolve_environment_target(target, notebook)
    if provider_bootstrap_required(environment):
        raise click.exceptions.Exit(run_in_environment(environment, sys.argv[1:]))
    result = asyncio.run(
        create_view(
            notebook,
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
@click.option("--yes", is_flag=True, help="Remove the view without prompting.")
@json_option
def remove(
    view_name: str,
    target: Path | None,
    yes: bool,
    json_output: bool,
) -> None:
    """Remove one view and its source files."""
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
