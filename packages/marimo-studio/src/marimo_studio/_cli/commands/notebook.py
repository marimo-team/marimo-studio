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
    json_option,
    run_in_environment,
)
from marimo_studio._cli.environment import should_reenter
from marimo_studio._cli.help import ColoredCommand, ColoredGroup
from marimo_studio._cli.options import (
    runtime_timeout_option,
    target_option,
)
from marimo_studio._cli.output import echo_json, render_binding, render_inspection
from marimo_studio._cli.targets import (
    load_studio_target,
    resolve_environment_target,
    resolve_notebook,
)
from marimo_studio._notebook.records import CellSelector, InspectionContext
from marimo_studio.errors import ConfigurationError


@click.group("notebook", cls=ColoredGroup)
def notebook() -> None:
    """Inspect saved cells and name results for views."""


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
@click.option(
    "--context",
    type=click.Choice(("selected", "upstream")),
    default="selected",
    show_default=True,
    help="Include selected cells or their complete upstream context.",
)
@runtime_timeout_option
@json_option
def inspect(
    target: Path | None,
    include_code: bool,
    output_expressions: bool,
    runtime: bool,
    limit: int | None,
    cell_selectors: tuple[str, ...],
    context: InspectionContext,
    runtime_timeout: float,
    json_output: bool,
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
                context=context,
                limit=limit,
                runtime_timeout=runtime_timeout,
            )
        )
    if json_output:
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
@json_option
def bind(
    alias: str,
    target: Path | None,
    cell_selector: str,
    dry_run: bool,
    overwrite: bool,
    json_output: bool,
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
    if json_output:
        echo_json(result.to_dict())
        return
    render_binding(result)


notebook.add_command(inspect)
notebook.add_command(bind)
