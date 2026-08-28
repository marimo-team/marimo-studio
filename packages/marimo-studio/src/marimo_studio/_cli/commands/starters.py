"""List installed starting points for new pages."""

from __future__ import annotations

import asyncio

import click

from marimo_studio._authoring.workspace import starters as installed_starters
from marimo_studio._cli.catalog_output import render_starter
from marimo_studio._cli.diagnostics import json_option
from marimo_studio._cli.help import ColoredCommand
from marimo_studio._cli.output import echo_json


@click.command("starters", cls=ColoredCommand)
@json_option
def starters(json_output: bool) -> None:
    """List installed starting points for new pages."""
    records = asyncio.run(installed_starters())
    if json_output:
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
