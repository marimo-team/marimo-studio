"""List and inspect installed view starters."""

from __future__ import annotations

import click

from marimo_studio._cli.catalog_output import render_starter
from marimo_studio._cli.diagnostics import diagnostic_format_option
from marimo_studio._cli.help import ColoredCommand, ColoredGroup
from marimo_studio._cli.options import output_format_option
from marimo_studio._cli.output import echo_json
from marimo_studio._views.catalog import get_starter, starters


@click.group("starter", cls=ColoredGroup)
def starter() -> None:
    """Discover installed starting points for new views."""


@click.command("list", cls=ColoredCommand)
@output_format_option
@diagnostic_format_option
def list_starters(output_format: str) -> None:
    """List installed starters and availability."""
    records = starters()
    payload = {
        "schema": 1,
        "starters": [item.to_dict() for item in records],
    }
    if output_format == "json":
        echo_json(payload)
        return
    for index, item in enumerate(records):
        if index:
            click.echo()
        render_starter(item)


@click.command("show", cls=ColoredCommand)
@click.argument("identity")
@output_format_option
@diagnostic_format_option
def show_starter(identity: str, output_format: str) -> None:
    """Show one installed starter."""
    selected = get_starter(identity)
    if output_format == "json":
        echo_json(selected.to_dict())
        return
    render_starter(selected)


starter.add_command(list_starters)
starter.add_command(show_starter)
