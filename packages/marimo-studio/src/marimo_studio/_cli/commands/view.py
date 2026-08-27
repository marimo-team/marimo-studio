"""Create, activate, and remove Studio views."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import click

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
    render_view_inspection,
    render_view_removal,
    render_view_setup,
)
from marimo_studio._cli.targets import load_studio_target, resolve_notebook
from marimo_studio._views.api import create_view, remove_view
from marimo_studio._views.build import build_view_project
from marimo_studio._views.inspect import inspect_view as inspect_project
from marimo_studio.agent._client import activate_view
from marimo_studio.agent._transport import studio_server_connection
from marimo_studio.errors import LastViewError, ProtocolError


@click.group("view", cls=ColoredGroup)
def view() -> None:
    """Create, activate, and remove notebook views."""


def _stdin_is_interactive() -> bool:
    return sys.stdin.isatty()


@click.command("create", cls=ColoredCommand)
@target_argument
@click.option(
    "--name",
    metavar="NAME",
    help="Name the view. Defaults to the configured default or dashboard.",
)
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
    target: Path | None,
    name: str | None,
    starter: str | None,
    dry_run: bool,
    output_format: str,
) -> None:
    """Create a view for TARGET.

    Pass a notebook path when creating its first view. Configured targets may
    also be project directories or pyproject.toml files. The current directory
    is used when TARGET is omitted.
    """
    result = create_view(
        resolve_notebook(target),
        name,
        starter=starter,
        dry_run=dry_run,
    )
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
    short_help="Remove a complete view project.",
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
    """Remove a complete view project from TARGET.

    TARGET may be a notebook, project directory, or pyproject.toml. The current
    directory is used when TARGET is omitted.
    """
    studio = load_studio_target(target)
    studio.view(name)
    if len(studio.views) == 1:
        raise LastViewError()
    if not yes and (
        output_format == "json"
        or diagnostics().format == "jsonl"
        or not _stdin_is_interactive()
    ):
        raise click.UsageError(
            "Pass --yes for machine output or non-interactive input."
        )
    if not yes and not click.confirm(
        f"Remove view {name!r} and its project directory?",
        default=False,
        err=True,
    ):
        raise click.exceptions.Exit(1)
    result = remove_view(studio, name)
    if output_format == "json":
        echo_json(result.to_dict())
    else:
        render_view_removal(result)


@click.command("inspect", cls=ColoredCommand)
@target_argument
@click.option("--name", required=True, metavar="NAME", help="Name the view to inspect.")
@output_format_option
@diagnostic_format_option
def inspect_view(
    target: Path | None,
    name: str,
    output_format: str,
) -> None:
    """Inspect source documents, diagnostics, and publication state."""
    inspection = asyncio.run(inspect_project(load_studio_target(target), name))
    payload = inspection.to_dict()
    if output_format == "json":
        echo_json(payload)
        return
    render_view_inspection(inspection)


@click.command("build", cls=ColoredCommand)
@target_argument
@click.option("--name", required=True, metavar="NAME", help="Name the view to build.")
@click.option(
    "--profile",
    type=click.Choice(("development", "production")),
    default="development",
    show_default=True,
)
@output_format_option
@diagnostic_format_option
def build_view(
    target: Path | None,
    name: str,
    profile: str,
    output_format: str,
) -> None:
    """Build and publish one artifact inside a view project."""
    if profile != "development" and profile != "production":
        raise click.BadParameter("Unknown build profile", param_hint="--profile")
    publication = asyncio.run(
        build_view_project(
            load_studio_target(target).view(name),
            profile=profile,
        )
    )
    if output_format == "json":
        echo_json(publication.to_dict())
        return
    click.echo(f"Published {publication.profile} artifact {publication.artifact_id}")


view.add_command(create)
view.add_command(activate)
view.add_command(build_view)
view.add_command(inspect_view)
view.add_command(remove)
