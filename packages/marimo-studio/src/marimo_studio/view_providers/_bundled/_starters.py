"""Assemble packaged starter files for bundled view providers."""

from __future__ import annotations

import html
import json
import re
from collections.abc import Mapping
from importlib import resources
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import TYPE_CHECKING

from marimo_studio.view_providers import ProviderStarter, StarterContext

if TYPE_CHECKING:
    from importlib.resources.abc import Traversable

StarterCatalog = Mapping[str, ProviderStarter]

_SHARED_DIRECTORY = "_shared"
_MARKERS = (
    "__NOTEBOOK_NAME_HTML__",
    "__VIEW_NAME_HTML__",
    "__VIEW_HEADING_HTML__",
    "__NOTEBOOK_NAME_JSON__",
    "__VIEW_NAME_JSON__",
    "__VIEW_HEADING_JSON__",
)
_MARKER_PATTERN = re.compile("|".join(re.escape(marker) for marker in _MARKERS))


def starter_catalog(*starters: ProviderStarter) -> StarterCatalog:
    """Index bundled starters by their provider-local keys."""
    records: dict[str, ProviderStarter] = {}
    for starter in starters:
        if starter.key in records:
            raise ValueError(f"Duplicate bundled starter {starter.key!r}")
        records[starter.key] = starter
    return MappingProxyType(records)


def _replacements(context: StarterContext) -> dict[str, str]:
    heading = context.view_name.replace("-", " ").title()
    return {
        "__NOTEBOOK_NAME_HTML__": html.escape(context.notebook_name),
        "__VIEW_NAME_HTML__": html.escape(context.view_name),
        "__VIEW_HEADING_HTML__": html.escape(heading),
        "__NOTEBOOK_NAME_JSON__": json.dumps(context.notebook_name),
        "__VIEW_NAME_JSON__": json.dumps(context.view_name),
        "__VIEW_HEADING_JSON__": json.dumps(heading),
    }


def _tree_files(
    root: Traversable,
    replacements: Mapping[str, str],
) -> dict[PurePosixPath, bytes]:
    files: dict[PurePosixPath, bytes] = {}

    def visit(node: Traversable, prefix: PurePosixPath) -> None:
        for child in sorted(node.iterdir(), key=lambda item: item.name):
            relative = prefix / child.name
            if child.is_dir():
                visit(child, relative)
                continue
            source = child.read_text(encoding="utf-8")
            rendered = _MARKER_PATTERN.sub(
                lambda match: replacements[match.group(0)],
                source,
            )
            files[relative] = rendered.encode()

    visit(root, PurePosixPath())
    return files


def starter_files(
    package: str,
    catalog: StarterCatalog,
    requested: ProviderStarter,
    context: StarterContext,
) -> dict[PurePosixPath, bytes]:
    """Render one bundled starter from provider-wide and starter-specific files."""
    starter = catalog.get(requested.key)
    if starter is None:
        raise ValueError(f"Unknown bundled starter {requested.key!r}")
    if starter != requested:
        raise ValueError(
            f"Bundled starter {requested.key!r} does not match its catalog"
        )

    root = resources.files(package).joinpath("starters")
    selected = root.joinpath(*PurePosixPath(starter.key).parts)
    if not selected.is_dir():
        raise ValueError(
            f"Bundled starter {starter.key!r} is missing from package {package!r}"
        )

    replacements = _replacements(context)
    shared = root.joinpath(_SHARED_DIRECTORY)
    sources = (shared, selected) if shared.is_dir() else (selected,)
    files: dict[PurePosixPath, bytes] = {}
    for source in sources:
        for path, payload in _tree_files(source, replacements).items():
            if path in files:
                raise ValueError(
                    f"Bundled starter {starter.key!r} defines {path.as_posix()!r} "
                    "more than once"
                )
            files[path] = payload

    missing = sorted(set(starter.documents) - files.keys())
    if missing:
        raise ValueError(
            f"Bundled starter {starter.key!r} is missing {missing[0].as_posix()!r}"
        )
    return dict(sorted(files.items(), key=lambda item: item[0].as_posix()))
