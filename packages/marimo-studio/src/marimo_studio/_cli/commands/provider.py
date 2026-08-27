"""Diagnose installed view provider registrations."""

from __future__ import annotations

import click

from marimo_studio._cli.catalog_output import render_provider
from marimo_studio._cli.diagnostics import diagnostic_format_option
from marimo_studio._cli.help import ColoredCommand, ColoredGroup
from marimo_studio._cli.options import output_format_option
from marimo_studio._cli.output import echo_json
from marimo_studio.errors import ConfigurationError
from marimo_studio.view_providers._host import provider_registry


@click.group("provider", cls=ColoredGroup)
def provider() -> None:
    """Diagnose installed frontend extensions."""


@click.command("doctor", cls=ColoredCommand)
@click.argument("selected_key", required=False)
@output_format_option
@diagnostic_format_option
def doctor(selected_key: str | None, output_format: str) -> None:
    """Check provider registration, availability, and starters."""
    registry = provider_registry()
    records = [
        diagnostic.to_dict()
        for diagnostic in registry.diagnostics()
        if selected_key is None or diagnostic.provider_key == selected_key
    ]
    if selected_key is not None and not records:
        raise ConfigurationError(f"Unknown view provider {selected_key!r}")
    payload = {"schema": 1, "providers": records}
    if output_format == "json":
        echo_json(payload)
        return
    for record in records:
        render_provider(record)


provider.add_command(doctor)
