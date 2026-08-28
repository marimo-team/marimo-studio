"""Describe Studio workspace state before authoring."""

from __future__ import annotations

import asyncio
from pathlib import Path

import click

from marimo_studio._authoring.workspace import status as workspace_status
from marimo_studio._cli.diagnostics import json_option
from marimo_studio._cli.help import ColoredCommand
from marimo_studio._cli.options import target_option
from marimo_studio._cli.output import echo_json, render_status
from marimo_studio._cli.targets import resolve_notebook


@click.command("status", cls=ColoredCommand)
@target_option
@json_option
def status(target: Path | None, json_output: bool) -> None:
    """Describe Studio configuration and pages."""
    result = asyncio.run(workspace_status(resolve_notebook(target)))
    if json_output:
        echo_json(result.to_dict())
        return
    render_status(result)
