"""Diagnose installed view provider registrations."""

from __future__ import annotations

import asyncio

import click

from marimo_studio._authoring.workspace import diagnose_providers
from marimo_studio._cli.catalog_output import render_provider
from marimo_studio._cli.diagnostics import diagnostic_format_option
from marimo_studio._cli.help import ColoredCommand
from marimo_studio._cli.options import output_format_option
from marimo_studio._cli.output import echo_json


@click.command("doctor", cls=ColoredCommand)
@click.argument("provider", required=False)
@output_format_option
@diagnostic_format_option
def doctor(provider: str | None, output_format: str) -> None:
    """Check provider registration, availability, and starters."""
    report = asyncio.run(diagnose_providers(provider))
    if output_format == "json":
        echo_json(report.to_dict())
        return
    for record in report.providers:
        render_provider(record.to_dict())
