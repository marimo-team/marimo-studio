"""Create starter projects from files a provider ships as package data."""

from __future__ import annotations

import html
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from importlib import resources
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import TYPE_CHECKING

from marimo_studio.view_providers._records import (
    ProviderStarter,
    StarterCellTarget,
    StarterContext,
    StarterPlan,
)

if TYPE_CHECKING:
    from importlib.resources.abc import Traversable

_MARKER_NAME = re.compile(r"__[A-Z0-9_]+__")
_LINE_SEPARATOR = re.compile(r"\r\n|\r|\n")


@dataclass(frozen=True)
class StarterMarkers:
    """Values for one starter's ``__MARKER__`` placeholders and the cells it names."""

    values: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    cell_targets: tuple[StarterCellTarget, ...] = ()


def _no_markers(context: StarterContext) -> StarterMarkers:
    del context
    return StarterMarkers()


@dataclass(frozen=True)
class PackagedStarter:
    """A starter whose files live in ``<package>/files``.

    ``markers`` returns the values for the starter's own ``__MARKER__``
    placeholders. Every starter can also use ``__NOTEBOOK_LABEL_HTML__``,
    ``__VIEW_HEADING_HTML__``, ``__NOTEBOOK_LABEL_JSON__``, and
    ``__VIEW_HEADING_JSON__``.
    """

    info: ProviderStarter
    package: str
    markers: Callable[[StarterContext], StarterMarkers] = _no_markers


def script_json(value: str) -> str:
    """Return a JSON string literal that cannot close an HTML ``<script>`` element."""
    return (
        json.dumps(value, ensure_ascii=False)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def _replacements(
    context: StarterContext,
    additions: Mapping[str, str],
) -> dict[str, str]:
    heading = context.view_name.replace("-", " ").title()
    label = context.notebook_label
    replacements = {
        "__NOTEBOOK_LABEL_HTML__": html.escape(label),
        "__VIEW_HEADING_HTML__": html.escape(heading),
        "__NOTEBOOK_LABEL_JSON__": script_json(label),
        "__VIEW_HEADING_JSON__": script_json(heading),
    }
    for marker, value in additions.items():
        if _MARKER_NAME.fullmatch(marker) is None:
            raise ValueError(f"Invalid starter marker {marker!r}")
        if marker in replacements:
            raise ValueError(f"Duplicate starter marker {marker!r}")
        replacements[marker] = value
    return replacements


def _tree_files(
    root: Traversable,
    replacements: Mapping[str, str],
    marker_pattern: re.Pattern[str],
) -> dict[PurePosixPath, bytes]:
    files: dict[PurePosixPath, bytes] = {}

    def visit(node: Traversable, prefix: PurePosixPath) -> None:
        for child in sorted(node.iterdir(), key=lambda item: item.name):
            relative = prefix / child.name
            if child.is_dir():
                visit(child, relative)
                continue
            payload = child.read_bytes()
            try:
                source = payload.decode("utf-8")
            except UnicodeDecodeError:
                files[relative] = payload
                continue
            separators = _LINE_SEPARATOR.findall(source)
            line_separator = (
                separators[0]
                if separators and all(item == separators[0] for item in separators)
                else None
            )

            def replacement(
                match: re.Match[str],
                separator: str | None = line_separator,
            ) -> str:
                value = replacements[match.group(0)]
                if separator is None:
                    return value
                normalized = _LINE_SEPARATOR.sub("\n", value)
                return normalized.replace("\n", separator)

            files[relative] = marker_pattern.sub(replacement, source).encode()

    visit(root, PurePosixPath())
    return files


def create_starter(
    starters: Sequence[PackagedStarter],
    requested: ProviderStarter,
    context: StarterContext,
) -> StarterPlan:
    """Render the requested starter's files with its marker values.

    Raises ``ValueError`` when ``requested`` is not one of ``starters`` or a
    document it lists is missing from its files.
    """
    starter = next((item for item in starters if item.info == requested), None)
    if starter is None:
        raise ValueError(f"Unknown starter {requested.key!r}")
    selected = resources.files(starter.package).joinpath("files")
    if not selected.is_dir():
        raise ValueError(f"Starter {requested.key!r} has no files in {starter.package}")
    markers = starter.markers(context)
    values = _replacements(context, markers.values)
    marker_pattern = re.compile(
        "|".join(re.escape(marker) for marker in sorted(values, key=len, reverse=True))
    )
    files = _tree_files(selected, values, marker_pattern)
    missing = sorted(set(requested.documents) - files.keys())
    if missing:
        raise ValueError(
            f"Starter {requested.key!r} is missing {missing[0].as_posix()!r}"
        )
    return StarterPlan(
        files=dict(sorted(files.items(), key=lambda item: item[0].as_posix())),
        cell_targets=markers.cell_targets,
    )
