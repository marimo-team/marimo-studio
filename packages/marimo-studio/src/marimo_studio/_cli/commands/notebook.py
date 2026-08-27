"""Inspect notebook cells and bind stable aliases."""

from __future__ import annotations

import asyncio
import sys
from contextlib import nullcontext
from pathlib import Path

import click

from marimo_studio._authoring.workspace import bind_cell
from marimo_studio._authoring.workspace import (
    inspect_notebook as inspect_notebook_cells,
)
from marimo_studio._cli.diagnostics import (
    capture_runtime_stderr,
    diagnostic_format_option,
    run_in_environment,
)
from marimo_studio._cli.environment import should_reenter
from marimo_studio._cli.help import ColoredCommand, ColoredGroup
from marimo_studio._cli.options import (
    output_format_option,
    runtime_timeout_option,
    target_option,
)
from marimo_studio._cli.output import echo_json, render_binding, render_inspection
from marimo_studio._cli.targets import (
    load_studio_target,
    resolve_environment_target,
    resolve_notebook,
)
from marimo_studio._notebook.records import CellSelector
from marimo_studio.errors import ConfigurationError


@click.group("notebook", cls=ColoredGroup)
def notebook() -> None:
    """Inspect saved cells and manage view-facing aliases."""


@click.command("inspect", cls=ColoredCommand)
@target_option
@click.option("--include-code", is_flag=True, help="Include complete cell source.")
@click.option(
    "--output-expressions",
    is_flag=True,
    help="Return cells with a final output expression.",
)
@click.option(
    "--runtime",
    is_flag=True,
    help="Execute the notebook and include MIME outputs and JSON values.",
)
@click.option("--limit", type=click.IntRange(min=1), help="Limit cell records.")
@click.option(
    "--cell",
    "cell_selectors",
    multiple=True,
    help="Select a cell by ref, name, or zero-based index. Repeat to select more.",
)
@runtime_timeout_option
@output_format_option
@diagnostic_format_option
def inspect(
    target: Path | None,
    include_code: bool,
    output_expressions: bool,
    runtime: bool,
    limit: int | None,
    cell_selectors: tuple[str, ...],
    runtime_timeout: float,
    output_format: str,
) -> None:
    """Inspect cells in a saved notebook."""
    notebook_path = resolve_notebook(target)
    if not notebook_path.is_file():
        raise ConfigurationError(f"Notebook does not exist: {notebook_path}")
    selectors: tuple[CellSelector, ...] = tuple(
        int(selector) if selector.isdecimal() else selector
        for selector in cell_selectors
    )
    if runtime:
        environment = resolve_environment_target(target, notebook_path)
        if should_reenter(environment, None):
            raise click.exceptions.Exit(run_in_environment(environment, sys.argv[1:]))
    with capture_runtime_stderr() if runtime else nullcontext():
        result = asyncio.run(
            inspect_notebook_cells(
                notebook_path,
                runtime=runtime,
                include_code=include_code,
                selectors=selectors,
                output_expressions=output_expressions,
                limit=limit,
                runtime_timeout=runtime_timeout,
            )
        )
    if output_format == "json":
        echo_json(result.to_dict())
        return
    render_inspection(result)


@click.command("bind", cls=ColoredCommand)
@click.argument("alias")
@target_option
@click.option(
    "--cell",
    "cell_selector",
    required=True,
    help="Select a cell by ref, name, or zero-based index.",
)
@click.option("--dry-run", is_flag=True, help="Report the binding without writing.")
@click.option("--overwrite", is_flag=True, help="Replace an existing binding.")
@output_format_option
@diagnostic_format_option
def bind(
    alias: str,
    target: Path | None,
    cell_selector: str,
    dry_run: bool,
    overwrite: bool,
    output_format: str,
) -> None:
    """Bind an alias to one saved notebook cell."""
    selector: CellSelector = (
        int(cell_selector) if cell_selector.isdecimal() else cell_selector
    )
    result = asyncio.run(
        bind_cell(
            load_studio_target(target).notebook,
            alias,
            selector,
            dry_run=dry_run,
            overwrite=overwrite,
        )
    )
    if output_format == "json":
        echo_json(result.to_dict())
        return
    render_binding(result)


notebook.add_command(inspect)
notebook.add_command(bind)
