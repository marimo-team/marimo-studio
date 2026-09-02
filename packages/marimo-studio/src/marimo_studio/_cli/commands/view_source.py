"""Inspect, read, and write Studio view source."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import BinaryIO

import click

from marimo_studio._authoring.view import (
    inspect_view,
    read_document_with_owner,
    write_document,
)
from marimo_studio._cli.diagnostics import json_option, run_in_environment
from marimo_studio._cli.environment import (
    EnvironmentTarget,
    provider_bootstrap_required,
)
from marimo_studio._cli.help import ColoredCommand
from marimo_studio._cli.input import read_source_input
from marimo_studio._cli.options import (
    owner_generation_type,
    target_option,
    view_name_argument,
)
from marimo_studio._cli.output import (
    echo_json,
    render_document_write,
    render_view_document,
    render_view_inspection,
)
from marimo_studio._cli.targets import resolve_environment_target, resolve_notebook
from marimo_studio._views.sources import admit_source_owner, source_path
from marimo_studio._workspace.project_manifest import VIEW_MANIFEST_PATH


def _bootstrap_provider_environment(environment: EnvironmentTarget) -> None:
    if provider_bootstrap_required(environment):
        raise click.exceptions.Exit(run_in_environment(environment, sys.argv[1:]))


@click.command("inspect", cls=ColoredCommand)
@view_name_argument
@target_option
@json_option
def inspect(
    view_name: str,
    target: Path | None,
    json_output: bool,
) -> None:
    """Inspect source documents, diagnostics, and development build state.

    When needed, Studio reruns the command through uv with requirements derived
    from the target's saved views and Python metadata. uv may resolve and install
    packages before provider code loads. Reviewed provider code then runs with
    the current user's filesystem, environment, and network authority.
    """
    notebook = resolve_notebook(target)
    environment = resolve_environment_target(target, notebook)
    _bootstrap_provider_environment(environment)
    result = asyncio.run(inspect_view(notebook, view_name))
    if json_output:
        echo_json(result.to_dict())
        return
    render_view_inspection(result)


@click.command("read", cls=ColoredCommand)
@view_name_argument
@click.argument("path")
@target_option
@json_option
def read(
    view_name: str,
    path: str,
    target: Path | None,
    json_output: bool,
) -> None:
    """Read one allowed source document and its revision.

    Use --json to obtain every precondition required by view write.

    When needed, Studio reruns the command through uv with requirements derived
    from the target's saved views and Python metadata. uv may resolve and install
    packages before provider code loads. Reviewed provider code then runs with
    the current user's filesystem, environment, and network authority. The
    view.toml repair path stays in the current Studio environment.
    """
    notebook = resolve_notebook(target)
    document_path = source_path(path)
    environment = resolve_environment_target(target, notebook)
    if document_path != VIEW_MANIFEST_PATH:
        _bootstrap_provider_environment(environment)
    snapshot = asyncio.run(read_document_with_owner(notebook, view_name, document_path))
    if json_output:
        echo_json({"schema": 1, **snapshot.to_dict()})
        return
    render_view_document(snapshot.document)


@click.command("write", cls=ColoredCommand)
@view_name_argument
@click.argument("path")
@target_option
@click.option(
    "--expected-revision",
    required=True,
    metavar="REVISION",
    help="Write when the current document has this revision.",
)
@click.option(
    "--catalog-generation",
    required=True,
    type=owner_generation_type,
    metavar="GENERATION",
    help="Write when the workspace catalog has this generation.",
)
@click.option(
    "--view-generation",
    required=True,
    type=owner_generation_type,
    metavar="GENERATION",
    help="Write when the named view has this generation.",
)
@click.option(
    "--from",
    "source",
    required=True,
    type=click.File("rb"),
    metavar="FILE|-",
    help="Read replacement UTF-8 content from a file or standard input.",
)
@json_option
def write(
    view_name: str,
    path: str,
    target: Path | None,
    expected_revision: str,
    catalog_generation: str,
    view_generation: str,
    source: BinaryIO,
    json_output: bool,
) -> None:
    """Conditionally replace one allowed source document.

    When needed, Studio reruns the command through uv with requirements derived
    from the target's saved views and Python metadata. uv may resolve and install
    packages before provider code loads. Reviewed provider code then runs with
    the current user's filesystem, environment, and network authority. The
    view.toml repair path stays in the current Studio environment.
    """
    notebook = resolve_notebook(target)
    document_path = source_path(path)
    environment = resolve_environment_target(target, notebook)
    admit_source_owner(
        notebook,
        view_name,
        expected_catalog_generation=catalog_generation,
        expected_generation=view_generation,
    )
    if document_path != VIEW_MANIFEST_PATH:
        _bootstrap_provider_environment(environment)
    document = asyncio.run(
        write_document(
            notebook,
            view_name,
            document_path,
            read_source_input(source),
            expected_revision=expected_revision,
            expected_catalog_generation=catalog_generation,
            expected_generation=view_generation,
        )
    )
    if json_output:
        echo_json({"schema": 1, **document.to_dict()})
        return
    render_document_write(document)
