"""Describe Studio workspace state before authoring."""

from __future__ import annotations

from pathlib import Path

import click

from marimo_studio._cli.diagnostics import diagnostic_format_option
from marimo_studio._cli.help import ColoredCommand
from marimo_studio._cli.options import output_format_option, target_argument
from marimo_studio._cli.output import echo_json, render_overview
from marimo_studio._cli.targets import resolve_notebook
from marimo_studio._views.overview import overview as inspect_overview


@click.command("overview", cls=ColoredCommand)
@target_argument
@output_format_option
@diagnostic_format_option
def overview(target: Path | None, output_format: str) -> None:
    """Describe Studio configuration and views for TARGET.

    Pass a notebook path before its first view is configured. Configured targets
    may also be project directories or pyproject.toml files.
    """
    result = inspect_overview(resolve_notebook(target))
    if output_format == "json":
        echo_json(result.to_dict())
    else:
        render_overview(result)
