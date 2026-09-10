"""Coordinate publication while source is edited through any filesystem tool."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import click

from marimo_studio._authoring.view import hold_publication, release_publication
from marimo_studio._cli.diagnostics import json_option
from marimo_studio._cli.help import ColoredCommand
from marimo_studio._cli.options import target_option, view_name_argument
from marimo_studio._cli.output import echo_json
from marimo_studio._cli.targets import resolve_notebook
from marimo_studio._views.publication_hold import (
    DEFAULT_PUBLICATION_HOLD_SECONDS,
    MAX_PUBLICATION_HOLD_SECONDS,
)


@click.command("hold", cls=ColoredCommand)
@view_name_argument
@target_option
@click.option(
    "--owner", required=True, help="Identify the editor coordinating this hold."
)
@click.option(
    "--ttl",
    type=click.FloatRange(min=0, min_open=True, max=MAX_PUBLICATION_HOLD_SECONDS),
    default=DEFAULT_PUBLICATION_HOLD_SECONDS,
    show_default=True,
    help="Expire the hold after this many seconds.",
)
@json_option
def hold(
    view_name: str, target: Path | None, owner: str, ttl: float, json_output: bool
) -> None:
    """Retain the published view while editing source files.

    Release with the returned token. Expiry resumes automatic publication even
    when the editing process exits before release. Source files stay on disk.
    """
    result = asyncio.run(
        hold_publication(resolve_notebook(target), view_name, owner=owner, ttl=ttl)
    )
    if json_output:
        echo_json({"schema": 1, "view": view_name, **result.to_dict()})
        return
    expires = datetime.fromtimestamp(result.expires_at, timezone.utc).isoformat()
    click.echo(f"Publication held by {result.owner} until {expires}")
    click.echo(f"Release token: {result.token}")


@click.command("release", cls=ColoredCommand)
@view_name_argument
@target_option
@click.option(
    "--token", required=True, help="Release the publication hold with this token."
)
@json_option
def release(view_name: str, target: Path | None, token: str, json_output: bool) -> None:
    """Release a matching publication hold and allow current source to build."""
    result = asyncio.run(
        release_publication(resolve_notebook(target), view_name, token)
    )
    if json_output:
        echo_json(
            {
                "schema": 1,
                "view": view_name,
                "hold": result.to_dict() if result else None,
            }
        )
        return
    click.echo(f"Publication released for {view_name}")
