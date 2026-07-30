"""Create and list Studio views."""

from __future__ import annotations

from pathlib import Path

import click

from marimo_studio._cli.diagnostics import diagnostic_format_option
from marimo_studio._cli.help import ColoredCommand, ColoredGroup
from marimo_studio._cli.options import notebook_argument, output_format_option
from marimo_studio._cli.output import (
    echo_json,
    render_view_list,
    render_view_setup,
    view_list_payload,
)
from marimo_studio._workspace.setup import ensure_view
from marimo_studio._workspace.targets import load_studio_target, resolve_notebook


@click.group("view", cls=ColoredGroup)
def view() -> None:
    """Create and list notebook views."""


@click.command("add", cls=ColoredCommand)
@click.argument("name")
@notebook_argument
@click.option("--dry-run", is_flag=True, help="Report changes without writing.")
@output_format_option
@diagnostic_format_option
def add(
    name: str,
    notebook: Path | None,
    dry_run: bool,
    output_format: str,
) -> None:
    """Add the named view to NOTEBOOK."""
    result = ensure_view(resolve_notebook(notebook), name, dry_run=dry_run)
    if output_format == "json":
        echo_json(result.to_dict())
    else:
        render_view_setup(result)


@click.command("list", cls=ColoredCommand)
@notebook_argument
@output_format_option
@diagnostic_format_option
def list_views(notebook: Path | None, output_format: str) -> None:
    """List views configured for NOTEBOOK."""
    studio = load_studio_target(notebook)
    if output_format == "json":
        echo_json(view_list_payload(studio))
    else:
        render_view_list(studio)


view.add_command(add)
view.add_command(list_views)
