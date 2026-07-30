"""Bind stable aliases to notebook cells."""

from __future__ import annotations

from pathlib import Path

import click

from marimo_studio._cli.diagnostics import diagnostic_format_option
from marimo_studio._cli.help import ColoredCommand
from marimo_studio._cli.options import notebook_argument, output_format_option
from marimo_studio._cli.output import (
    binding_payload,
    echo_json,
    render_binding,
)
from marimo_studio._workspace.bindings import bind_cell
from marimo_studio._workspace.targets import load_studio_target


@click.command("bind", cls=ColoredCommand)
@click.argument("alias")
@notebook_argument
@click.option(
    "--cell",
    "cell_index",
    required=True,
    type=click.IntRange(min=0),
    help="Select a zero-based notebook cell.",
)
@click.option("--dry-run", is_flag=True, help="Report the binding without writing.")
@click.option("--overwrite", is_flag=True, help="Replace an existing binding.")
@output_format_option
@diagnostic_format_option
def bind(
    alias: str,
    notebook: Path | None,
    cell_index: int,
    dry_run: bool,
    overwrite: bool,
    output_format: str,
) -> None:
    """Bind ALIAS to a cell in NOTEBOOK."""
    result = bind_cell(
        load_studio_target(notebook),
        alias,
        cell_index,
        dry_run=dry_run,
        overwrite=overwrite,
    )
    if output_format == "json":
        echo_json(binding_payload(result, dry_run=dry_run))
    else:
        render_binding(result, dry_run=dry_run)
