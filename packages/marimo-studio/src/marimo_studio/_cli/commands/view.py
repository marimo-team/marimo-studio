"""Create, list, and remove Studio views."""

from __future__ import annotations

from pathlib import Path

import click

from marimo_studio._cli.diagnostics import diagnostic_format_option, diagnostics
from marimo_studio._cli.help import ColoredCommand, ColoredGroup
from marimo_studio._cli.options import output_format_option, target_argument
from marimo_studio._cli.output import (
    echo_json,
    render_view_list,
    render_view_removal,
    render_view_setup,
    view_list_payload,
    view_removal_payload,
)
from marimo_studio._workspace.targets import load_studio_target, resolve_notebook
from marimo_studio._workspace.views import delete_view
from marimo_studio.errors import LastViewError, ViewNotFoundError
from marimo_studio.workspace import ensure_view


@click.group("view", cls=ColoredGroup)
def view() -> None:
    """Create, list, and remove notebook views."""


@click.command("add", cls=ColoredCommand)
@target_argument
@click.option(
    "--name",
    metavar="NAME",
    help="Name the view. Defaults to the configured default or dashboard.",
)
@click.option("--dry-run", is_flag=True, help="Report changes without writing.")
@output_format_option
@diagnostic_format_option
def add(
    target: Path | None,
    name: str | None,
    dry_run: bool,
    output_format: str,
) -> None:
    """Add a view to TARGET.

    Pass a notebook path when creating its first view. Configured targets may
    also be project directories or pyproject.toml files. The current directory
    is used when TARGET is omitted.
    """
    result = ensure_view(resolve_notebook(target), name, dry_run=dry_run)
    if output_format == "json":
        echo_json(result.to_dict())
    else:
        render_view_setup(result)


@click.command("list", cls=ColoredCommand)
@target_argument
@output_format_option
@diagnostic_format_option
def list_views(target: Path | None, output_format: str) -> None:
    """List views configured for TARGET.

    TARGET may be a notebook, project directory, or pyproject.toml. The current
    directory is used when TARGET is omitted.
    """
    studio = load_studio_target(target)
    if output_format == "json":
        echo_json(view_list_payload(studio))
    else:
        render_view_list(studio)


@click.command(
    "remove",
    cls=ColoredCommand,
    short_help="Remove a view and delete its source files.",
)
@target_argument
@click.option("--name", required=True, metavar="NAME", help="Name the view to remove.")
@click.option(
    "--yes",
    is_flag=True,
    help="Remove the view without prompting.",
)
@output_format_option
@diagnostic_format_option
def remove(
    target: Path | None,
    name: str,
    yes: bool,
    output_format: str,
) -> None:
    """Remove a view and its source files from TARGET.

    TARGET may be a notebook, project directory, or pyproject.toml. The current
    directory is used when TARGET is omitted.
    """
    studio = load_studio_target(target)
    if name not in studio.views:
        raise ViewNotFoundError(name)
    if len(studio.views) == 1:
        raise LastViewError()
    if not yes and diagnostics().format == "jsonl":
        raise click.UsageError("Pass --yes when using JSON Lines diagnostics.")
    if not yes and not click.confirm(
        f"Remove view {name!r} and delete its source directory?",
        default=False,
        err=True,
    ):
        raise click.exceptions.Exit(1)
    updated = delete_view(studio, name)
    if output_format == "json":
        echo_json(view_removal_payload(updated, name))
    else:
        render_view_removal(updated, name)


view.add_command(add)
view.add_command(list_views)
view.add_command(remove)
