"""Build, show, and export named Studio views."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import cast

import click

from marimo_studio._authoring.view import (
    build_view,
    export_view,
    preflight_view,
    show_view,
)
from marimo_studio._browser_client.transport import studio_server_connection
from marimo_studio._cli.activity import activity
from marimo_studio._cli.diagnostics import diagnostics, json_option, run_in_environment
from marimo_studio._cli.environment import provider_bootstrap_required
from marimo_studio._cli.help import ColoredCommand
from marimo_studio._cli.options import (
    browser_client_option,
    finite_timeout,
    server_option,
    target_option,
    view_name_argument,
)
from marimo_studio._cli.output import (
    echo_json,
    render_static_export,
    render_static_preflight,
    render_view_show,
)
from marimo_studio._cli.targets import (
    load_studio_target,
    resolve_environment_target,
    resolve_notebook,
)
from marimo_studio._delivery.export import (
    DEFAULT_STATIC_RUNTIME,
    StaticExportResult,
    StaticRuntime,
)
from marimo_studio._delivery.preflight import StaticPreflightReport
from marimo_studio.errors import ProtocolError
from marimo_studio.view_providers import BuildProfile


def _emit_preflight_issues(result: StaticPreflightReport) -> None:
    stream = diagnostics()
    for issue in result.issues:
        stream.emit(
            code=issue.code,
            message=issue.message,
            severity=issue.severity,
            status="fail" if issue.severity == "error" else "warn",
            details=issue.to_dict(),
        )


def _emit_export_warnings(result: StaticExportResult) -> None:
    stream = diagnostics()
    for warning in result.warnings:
        stream.emit(
            code=warning.code,
            message=warning.message,
            severity="warning",
            status="warn",
            details=warning.details,
        )


def _bootstrap_provider_environment(target: Path | None, notebook: Path) -> None:
    environment = resolve_environment_target(target, notebook)
    if provider_bootstrap_required(environment):
        raise click.exceptions.Exit(run_in_environment(environment, sys.argv[1:]))


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
    """Build one view's browser page for development or production.

    When needed, Studio reruns the command through uv with requirements derived
    from the target's saved views and Python metadata. uv may resolve and install
    packages before provider code loads. Reviewed provider code then runs with
    the current user's filesystem, environment, and network authority.
    """
    notebook = resolve_notebook(target)
    _bootstrap_provider_environment(target, notebook)
    result = asyncio.run(
        build_view(
            notebook,
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
    """Show one view in a connected Studio tab."""
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
@click.option(
    "--runtime",
    type=click.Choice(("zero-python", "wasm")),
    default=DEFAULT_STATIC_RUNTIME,
    show_default=True,
    help=(
        "zero-python prepares configured notebook states during export. wasm runs "
        "notebook Python in each visitor's browser."
    ),
)
@click.option("--force", is_flag=True, help="Replace an existing output directory.")
@click.option(
    "--prepare-timeout",
    type=click.FloatRange(min=0, min_open=True),
    callback=finite_timeout,
    default=None,
    metavar="SECONDS",
    help=(
        "Seconds to wait for Zero-Python notebook preparation. Defaults to 30 "
        "seconds when omitted."
    ),
)
@json_option
def export(
    view_name: str,
    target: Path | None,
    output: Path,
    runtime: StaticRuntime,
    force: bool,
    prepare_timeout: float | None,
    json_output: bool,
) -> None:
    """Export one view as a static site.

    When needed, Studio reruns the command through uv with requirements derived
    from the target's saved views and Python metadata. uv may resolve and install
    packages before provider code loads. Reviewed provider code then runs with
    the current user's filesystem, environment, and network authority.
    """
    if runtime == "wasm" and prepare_timeout is not None:
        raise click.UsageError(
            "--prepare-timeout is only valid with --runtime zero-python."
        )
    notebook = resolve_notebook(target)
    _bootstrap_provider_environment(target, notebook)
    with activity(diagnostics(), phase="export", view=view_name) as progress:
        result = asyncio.run(
            export_view(
                notebook,
                view_name,
                output,
                runtime=runtime,
                force=force,
                prepare_timeout=prepare_timeout,
                progress=progress,
            )
        )
    _emit_export_warnings(result)
    _emit_preflight_issues(result.preflight)
    if json_output:
        echo_json(result.to_dict())
        return
    render_static_export(result)


@click.command("preflight", cls=ColoredCommand)
@view_name_argument
@target_option
@click.option(
    "--runtime",
    type=click.Choice(("zero-python", "wasm")),
    default=DEFAULT_STATIC_RUNTIME,
    show_default=True,
    help=(
        "zero-python verifies configured prepared states. wasm verifies the "
        "browser artifact and projection support."
    ),
)
@click.option(
    "--prepare-timeout",
    type=click.FloatRange(min=0, min_open=True),
    callback=finite_timeout,
    default=None,
    metavar="SECONDS",
    help=(
        "Seconds to wait for Zero-Python notebook preparation. Defaults to 30 "
        "seconds when omitted."
    ),
)
@json_option
def preflight(
    view_name: str,
    target: Path | None,
    runtime: StaticRuntime,
    prepare_timeout: float | None,
    json_output: bool,
) -> None:
    """Verify a static view without publishing an output directory.

    Studio builds the production artifact, prepares the selected runtime, and
    checks the staged browser references. The temporary bundle is discarded
    after validation.
    """
    if runtime == "wasm" and prepare_timeout is not None:
        raise click.UsageError(
            "--prepare-timeout is only valid with --runtime zero-python."
        )
    notebook = resolve_notebook(target)
    _bootstrap_provider_environment(target, notebook)
    with activity(diagnostics(), phase="preflight", view=view_name) as progress:
        result = asyncio.run(
            preflight_view(
                notebook,
                view_name,
                runtime=runtime,
                prepare_timeout=prepare_timeout,
                progress=progress,
            )
        )
    _emit_preflight_issues(result)
    if json_output:
        echo_json(result.to_dict())
    else:
        render_static_preflight(result)
