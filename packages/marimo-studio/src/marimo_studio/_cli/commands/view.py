"""Create, activate, and remove Studio views."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import click

from marimo_studio._agent_transport import studio_server_connection
from marimo_studio._cli.diagnostics import diagnostic_format_option, diagnostics
from marimo_studio._cli.help import ColoredCommand, ColoredGroup
from marimo_studio._cli.options import (
    browser_client_option,
    output_format_option,
    server_option,
    target_argument,
)
from marimo_studio._cli.output import (
    echo_json,
    render_view_activation,
    render_view_removal,
    render_view_setup,
)
from marimo_studio._workspace.targets import load_studio_target, resolve_notebook
from marimo_studio.activation import activate_view
from marimo_studio.errors import LastViewError, ProtocolError
from marimo_studio.workspace import ensure_view, remove_view


@click.group("view", cls=ColoredGroup)
def view() -> None:
    """Create, activate, and remove notebook views."""


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


@click.command("activate", cls=ColoredCommand)
@target_argument
@click.option(
    "--name", required=True, metavar="NAME", help="Name the view to activate."
)
@server_option(required=True)
@browser_client_option
@output_format_option
@diagnostic_format_option
def activate(
    target: Path | None,
    name: str,
    server_url: str,
    browser_client: str | None,
    output_format: str,
) -> None:
    """Activate a view in one connected Studio browser."""
    studio = load_studio_target(target)
    try:
        connection = studio_server_connection(
            server_url,
            access_token=os.environ.get("MARIMO_STUDIO_ACCESS_TOKEN", ""),
            browser_client=browser_client or "",
        )
    except ProtocolError as error:
        raise click.BadParameter(str(error), param_hint="--server") from error
    result = asyncio.run(activate_view(studio, connection, name))
    if output_format == "json":
        echo_json(result.to_dict())
    else:
        render_view_activation(result)


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
    studio.view(name)
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
    result = remove_view(studio, name)
    if output_format == "json":
        echo_json(result.to_dict())
    else:
        render_view_removal(result)


view.add_command(add)
view.add_command(activate)
view.add_command(remove)
