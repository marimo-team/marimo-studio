"""Describe Studio workspace state before authoring."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import click

from marimo_studio._authoring.workspace import status as workspace_status
from marimo_studio._cli.diagnostics import json_option, run_in_environment
from marimo_studio._cli.environment import provider_bootstrap_required
from marimo_studio._cli.help import ColoredCommand
from marimo_studio._cli.options import target_option
from marimo_studio._cli.output import echo_json, render_status
from marimo_studio._cli.targets import resolve_environment_target, resolve_notebook


@click.command("status", cls=ColoredCommand)
@target_option
@json_option
def status(target: Path | None, json_output: bool) -> None:
    """Describe Studio configuration and views.

    When needed, Studio reruns the command through uv with requirements derived
    from the target's saved views and Python metadata. uv may resolve and install
    packages before provider code loads. Reviewed provider code then runs with
    the current user's filesystem, environment, and network authority.
    """
    notebook = resolve_notebook(target)
    environment = resolve_environment_target(target, notebook)
    if provider_bootstrap_required(environment):
        raise click.exceptions.Exit(run_in_environment(environment, sys.argv[1:]))
    result = asyncio.run(workspace_status(notebook))
    if json_output:
        echo_json(result.to_dict())
        return
    render_status(result)
