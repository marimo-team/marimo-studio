"""List installed starting points for new views."""

from __future__ import annotations

import asyncio
from pathlib import Path

import click

from marimo_studio._authoring.workspace import starters as installed_starters
from marimo_studio._cli.catalog_output import render_starter
from marimo_studio._cli.diagnostics import json_option
from marimo_studio._cli.help import ColoredCommand
from marimo_studio._cli.output import echo_json
from marimo_studio._cli.targets import resolve_notebook
from marimo_studio.errors import ConfigurationError


@click.command("starters", cls=ColoredCommand)
@click.option(
    "--target",
    type=click.Path(path_type=Path),
    help=(
        "Report availability for a notebook, project directory, or "
        "pyproject.toml, with the tools its pixi metadata declares."
    ),
)
@json_option
def starters(target: Path | None, json_output: bool) -> None:
    """List installed starting points for new views."""
    notebook = resolve_notebook(target) if target is not None else None
    if notebook is not None and not notebook.is_file():
        raise ConfigurationError(f"Notebook does not exist: {notebook}")
    records = asyncio.run(installed_starters(notebook))
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
