"""List installed starting points for new views."""

from __future__ import annotations

import asyncio

import click

from marimo_studio._authoring.workspace import starters as installed_starters
from marimo_studio._cli.catalog_output import render_starter
from marimo_studio._cli.diagnostics import diagnostic_format_option
from marimo_studio._cli.help import ColoredCommand
from marimo_studio._cli.options import output_format_option
from marimo_studio._cli.output import echo_json


@click.command("starters", cls=ColoredCommand)
@output_format_option
@diagnostic_format_option
def starters(output_format: str) -> None:
    """List installed view starters and their availability."""
    records = asyncio.run(installed_starters())
    if output_format == "json":
        echo_json(
            {
                "schema": 1,
                "starters": [starter.to_dict() for starter in records],
            }
        )
        return
    for index, starter in enumerate(records):
        if index:
            click.echo()
        render_starter(starter)
