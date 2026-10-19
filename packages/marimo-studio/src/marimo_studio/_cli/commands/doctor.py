"""Diagnose installed view provider registrations."""

from __future__ import annotations

import asyncio
from pathlib import Path

import click

from marimo_studio._authoring.workspace import diagnose_providers
from marimo_studio._cli.catalog_output import render_provider
from marimo_studio._cli.diagnostics import json_option
from marimo_studio._cli.help import ColoredCommand
from marimo_studio._cli.output import echo_json
from marimo_studio._cli.targets import resolve_notebook
from marimo_studio._validation.dependencies import diagnose_dependencies


@click.command("doctor", cls=ColoredCommand)
@click.argument("provider", required=False)
@click.option(
    "--dependencies",
    is_flag=True,
    help="Compare notebook, project, provider, and runtime dependencies.",
)
@click.option(
    "--target",
    type=click.Path(path_type=Path),
    help=(
        "Select a notebook, project directory, or pyproject.toml. Provider "
        "checks include the tools its pixi metadata declares. Defaults to the "
        "current Studio configuration with --dependencies."
    ),
)
@json_option
def doctor(
    provider: str | None, dependencies: bool, target: Path | None, json_output: bool
) -> None:
    """Check frontend integrations and starting points.

    Name a PROVIDER to check one provider. Pass --dependencies instead to
    compare a notebook's declared and installed dependencies.
    """
    if dependencies:
        if provider is not None:
            raise click.UsageError("PROVIDER cannot be combined with --dependencies.")
        result = diagnose_dependencies(resolve_notebook(target))
        if json_output:
            echo_json(result.to_dict())
        else:
            click.echo(f"Python: {result.python}")
            click.echo(f"Project: {result.project or 'standalone notebook'}")
            for issue in result.issues:
                click.echo(f"{issue.code}: {issue.message}")
            if result.ok:
                click.echo("Dependency declarations and runtime imports agree.")
        if not result.ok:
            raise click.exceptions.Exit(1)
        return
    notebook = resolve_notebook(target) if target is not None else None
    report = asyncio.run(diagnose_providers(provider, notebook))
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
