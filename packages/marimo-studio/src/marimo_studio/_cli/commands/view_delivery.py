"""Build, show, and export named Studio pages."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import cast

import click

from marimo_studio._authoring.view import build_view, export_view, show_view
from marimo_studio._browser_client.transport import studio_server_connection
from marimo_studio._cli.diagnostics import json_option
from marimo_studio._cli.help import ColoredCommand
from marimo_studio._cli.options import (
    browser_client_option,
    server_option,
    target_option,
    view_name_argument,
)
from marimo_studio._cli.output import (
    echo_json,
    render_static_export,
    render_view_show,
)
from marimo_studio._cli.targets import load_studio_target, resolve_notebook
from marimo_studio.errors import ProtocolError
from marimo_studio.view_providers import BuildProfile


@click.command("build", cls=ColoredCommand)
@view_name_argument
@target_option
@click.option(
    "--profile",
    type=click.Choice(("development", "production")),
    default="development",
    show_default=True,
)
@json_option
def build(
    view_name: str,
    target: Path | None,
    profile: str,
    json_output: bool,
) -> None:
    """Build one page for development or production."""
    result = asyncio.run(
        build_view(
            resolve_notebook(target),
            view_name,
            profile=cast(BuildProfile, profile),
        )
    )
    if json_output:
        echo_json(result.to_dict())
        return
    click.echo(f"Built {result.view} for {result.profile} use ({result.revision})")


@click.command("show", cls=ColoredCommand)
@view_name_argument
@target_option
@server_option(required=True)
@browser_client_option
@json_option
def show(
    view_name: str,
    target: Path | None,
    server_url: str,
    browser_client: str | None,
    json_output: bool,
) -> None:
    """Show one page in a connected Studio tab."""
    try:
        connection = studio_server_connection(
            server_url,
            access_token=os.environ.get("MARIMO_STUDIO_ACCESS_TOKEN", ""),
            browser_client=browser_client or "",
        )
    except ProtocolError as error:
        raise click.BadParameter(str(error), param_hint="--server") from error
    result = asyncio.run(
        show_view(
            load_studio_target(target).notebook,
            view_name,
            connection,
        )
    )
    if json_output:
        echo_json(result.to_dict())
        return
    render_view_show(result)


@click.command("export", cls=ColoredCommand)
@view_name_argument
@target_option
@click.option(
    "-o",
    "--output",
    type=click.Path(path_type=Path, file_okay=False),
    required=True,
    help="Write the static site to this directory.",
)
@click.option("--force", is_flag=True, help="Replace an existing output directory.")
@json_option
def export(
    view_name: str,
    target: Path | None,
    output: Path,
    force: bool,
    json_output: bool,
) -> None:
    """Export one page as a static WebAssembly site."""
    result = asyncio.run(
        export_view(
            resolve_notebook(target),
            view_name,
            output,
            force=force,
        )
    )
    if json_output:
        echo_json(result.to_dict())
        return
    render_static_export(result)
