"""Bind stable aliases to notebook cells."""

from __future__ import annotations

from pathlib import Path

import click

from marimo_studio._cli.diagnostics import diagnostic_format_option
from marimo_studio._cli.help import ColoredCommand
from marimo_studio._cli.options import output_format_option, target_argument
from marimo_studio._cli.output import (
    echo_json,
    render_binding,
)
from marimo_studio._cli.targets import load_studio_target
from marimo_studio._views.api import bind_cell


@click.command("bind", cls=ColoredCommand)
@target_argument
@click.option(
    "--cell",
    "cell_index",
    required=True,
    type=click.IntRange(min=0),
    help="Select a zero-based notebook cell.",
)
@click.option("--as", "alias", required=True, metavar="ALIAS", help="Name the cell.")
@click.option("--dry-run", is_flag=True, help="Report the binding without writing.")
@click.option("--overwrite", is_flag=True, help="Replace an existing binding.")
@output_format_option
@diagnostic_format_option
def bind(
    target: Path | None,
    cell_index: int,
    alias: str,
    dry_run: bool,
    overwrite: bool,
    output_format: str,
) -> None:
    """Bind a cell in TARGET as a stable alias.

    TARGET may be a notebook, project directory, or pyproject.toml. The current
    directory is used when TARGET is omitted.
    """
    result = bind_cell(
        load_studio_target(target),
        alias,
        cell_index,
        dry_run=dry_run,
        overwrite=overwrite,
    )
    if output_format == "json":
        echo_json(result.to_dict())
    else:
        render_binding(result)
