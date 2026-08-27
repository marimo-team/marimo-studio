"""Export a custom view as a static WebAssembly site."""

from __future__ import annotations

from pathlib import Path

import click

from marimo_studio._cli.diagnostics import diagnostic_format_option
from marimo_studio._cli.help import ColoredCommand
from marimo_studio._cli.options import output_format_option, target_argument
from marimo_studio._cli.output import echo_json, render_static_export
from marimo_studio._delivery.export import export_view


@click.command(
    "export",
    cls=ColoredCommand,
    short_help="Export a view as a static WebAssembly site.",
)
@target_argument
@click.option(
    "-o",
    "--output",
    type=click.Path(path_type=Path, file_okay=False),
    required=True,
    help="Write the static site to this directory.",
)
@click.option("--view", help="Export this view instead of the configured default.")
@click.option(
    "--force",
    is_flag=True,
    help="Replace an existing output directory.",
)
@output_format_option
@diagnostic_format_option
def export(
    target: Path | None,
    output: Path,
    view: str | None,
    force: bool,
    output_format: str,
) -> None:
    """Export a view from TARGET as a static WebAssembly site.

    TARGET may be a notebook, project directory, or pyproject.toml. The current
    directory is used when TARGET is omitted.
    """
    result = export_view(target or Path.cwd(), output, view=view, force=force)
    if output_format == "json":
        echo_json(result.to_dict())
    else:
        render_static_export(result)
