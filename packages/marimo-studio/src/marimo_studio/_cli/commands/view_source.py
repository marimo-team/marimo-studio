"""Inspect, read, and write Studio page source."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import BinaryIO

import click

from marimo_studio._authoring.view import (
    inspect_view,
    read_document,
    write_document,
)
from marimo_studio._cli.diagnostics import json_option
from marimo_studio._cli.help import ColoredCommand
from marimo_studio._cli.input import read_source_input
from marimo_studio._cli.options import (
    target_option,
    view_name_argument,
)
from marimo_studio._cli.output import (
    echo_json,
    render_document_write,
    render_view_document,
    render_view_inspection,
)
from marimo_studio._cli.targets import resolve_notebook


@click.command("inspect", cls=ColoredCommand)
@view_name_argument
@target_option
@json_option
def inspect(
    view_name: str,
    target: Path | None,
    json_output: bool,
) -> None:
    """Inspect source documents, diagnostics, and build state."""
    result = asyncio.run(inspect_view(resolve_notebook(target), view_name))
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
    """Read one allowed source document and its revision."""
    document = asyncio.run(read_document(resolve_notebook(target), view_name, path))
    if json_output:
        echo_json({"schema": 1, **document.to_dict()})
        return
    render_view_document(document)


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
    source: BinaryIO,
    json_output: bool,
) -> None:
    """Conditionally replace one allowed source document."""
    document = asyncio.run(
        write_document(
            resolve_notebook(target),
            view_name,
            path,
            read_source_input(source),
            expected_revision=expected_revision,
        )
    )
    if json_output:
        echo_json({"schema": 1, **document.to_dict()})
        return
    render_document_write(document)
