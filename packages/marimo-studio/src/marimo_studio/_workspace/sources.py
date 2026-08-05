"""Read and conditionally replace the authored files shown in Studio."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Final, Literal

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

SourceName = Literal["index.html", "theme.css", "app.css"]


@dataclass(frozen=True)
class SourceSpec:
    """One ordered authored file exposed by Studio."""

    name: SourceName
    optional: bool = False


SOURCE_SPECS: Final = (
    SourceSpec("index.html"),
    SourceSpec("theme.css", optional=True),
    SourceSpec("app.css"),
)
SOURCE_NAMES: Final = tuple(spec.name for spec in SOURCE_SPECS)
_SOURCE_SPECS: Final = {spec.name: spec for spec in SOURCE_SPECS}


@dataclass(frozen=True)
class SourceDocument:
    """One UTF-8 view file and its content-derived revision."""

    name: SourceName
    content: str
    revision: str


def _source_spec(name: str) -> SourceSpec:
    if name not in _SOURCE_SPECS:
        raise SourceNotFoundError(f"Unknown Studio source file {name!r}.")
    return _SOURCE_SPECS[name]


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
    source = _source_spec(name)
    path = _view(studio, view_name).root / source.name
    reject_mutable_symlinks(studio.notebook.parent, {path})
    if not path.is_file():
        if source.optional:
            return SourceDocument(source.name, "", _revision(""))
        raise SourceNotFoundError(f"{source.name} is missing from view {view_name!r}.")
    try:
        content = read_text(path)
    except UnicodeDecodeError as error:
        raise SourceEncodingError(
            f"{source.name} in view {view_name!r} must be UTF-8 text."
        ) from error
    return SourceDocument(source.name, content, _revision(content))


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
