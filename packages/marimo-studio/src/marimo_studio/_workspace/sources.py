"""Read and conditionally replace the authored files shown in Studio."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Final, Literal, cast

from marimo_studio._workspace.files import (
    atomic_write_text,
    read_text,
    reject_mutable_symlinks,
)
from marimo_studio._workspace.models import StudioConfig, View
from marimo_studio.errors import (
    SourceConflictError,
    SourceEncodingError,
    SourceNotFoundError,
)

SourceName = Literal["index.html", "app.css"]
SOURCE_NAMES: Final = frozenset({"index.html", "app.css"})


@dataclass(frozen=True)
class SourceDocument:
    """One UTF-8 view file and its content-derived revision."""

    name: SourceName
    content: str
    revision: str


def _source_name(name: str) -> SourceName:
    if name not in SOURCE_NAMES:
        raise SourceNotFoundError(f"Unknown Studio source file {name!r}.")
    return cast(SourceName, name)


def _view(studio: StudioConfig, view_name: str) -> View:
    try:
        return studio.views[view_name]
    except KeyError as error:
        raise SourceNotFoundError(f"Unknown view {view_name!r}.") from error


def _revision(content: str) -> str:
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def read_source(
    studio: StudioConfig,
    view_name: str,
    name: str,
) -> SourceDocument:
    """Return one supported source file with its current revision."""
    source_name = _source_name(name)
    path = _view(studio, view_name).root / source_name
    reject_mutable_symlinks(studio.notebook.parent, {path})
    if not path.is_file():
        raise SourceNotFoundError(f"{source_name} is missing from view {view_name!r}.")
    try:
        content = read_text(path)
    except UnicodeDecodeError as error:
        raise SourceEncodingError(
            f"{source_name} in view {view_name!r} must be UTF-8 text."
        ) from error
    return SourceDocument(source_name, content, _revision(content))


def write_source(
    studio: StudioConfig,
    view_name: str,
    name: str,
    content: str,
    expected_revision: str,
) -> SourceDocument:
    """Replace one source when its loaded revision is still current."""
    current = read_source(studio, view_name, name)
    if current.revision != expected_revision:
        raise SourceConflictError(current.name, current.revision)
    if content == current.content:
        return current
    path = _view(studio, view_name).root / current.name
    atomic_write_text(path, content)
    return SourceDocument(current.name, content, _revision(content))
