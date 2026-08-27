"""Describe Studio workspace state before authoring."""

from __future__ import annotations

import asyncio
from pathlib import Path

import click

from marimo_studio._authoring.workspace import status as workspace_status
from marimo_studio._cli.diagnostics import diagnostic_format_option
from marimo_studio._cli.help import ColoredCommand
from marimo_studio._cli.options import output_format_option, target_option
from marimo_studio._cli.output import echo_json, render_status
from marimo_studio._cli.targets import resolve_notebook


@click.command("status", cls=ColoredCommand)
@target_option
@output_format_option
@diagnostic_format_option
def status(target: Path | None, output_format: str) -> None:
    """Describe Studio configuration and views."""
    result = asyncio.run(workspace_status(resolve_notebook(target)))
    if output_format == "json":
        echo_json(result.to_dict())
        return
    render_status(result)
