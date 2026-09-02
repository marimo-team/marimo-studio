"""Diagnose installed view provider registrations."""

from __future__ import annotations

import asyncio

import click

from marimo_studio._authoring.workspace import diagnose_providers
from marimo_studio._cli.catalog_output import render_provider
from marimo_studio._cli.diagnostics import json_option
from marimo_studio._cli.help import ColoredCommand
from marimo_studio._cli.output import echo_json


@click.command("doctor", cls=ColoredCommand)
@click.argument("provider", required=False)
@json_option
def doctor(provider: str | None, json_output: bool) -> None:
    """Check frontend integrations and starting points."""
    report = asyncio.run(diagnose_providers(provider))
    if json_output:
        echo_json(report.to_dict())
    else:
        for record in report.providers:
            render_provider(record.to_dict())
    if provider is not None and not all(
        record.loaded
        and record.availability is not None
        and record.availability.available
        for record in report.providers
    ):
        raise click.exceptions.Exit(1)
