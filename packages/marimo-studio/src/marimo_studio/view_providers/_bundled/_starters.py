"""Assemble packaged starter files for bundled view providers."""

from __future__ import annotations

import html
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from importlib import resources
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import TYPE_CHECKING

from marimo_studio.view_providers import (
    CellSpec,
    ProviderStarter,
    StarterCellTarget,
    StarterContext,
    StarterPlan,
)

if TYPE_CHECKING:
    from importlib.resources.abc import Traversable


@dataclass(frozen=True)
class StarterRendering:
    """Describe one leaf starter's source substitutions and cell targets."""

    replacements: Mapping[str, str]
    cell_targets: tuple[StarterCellTarget, ...]


@dataclass(frozen=True)
class BundledStarter:
    """Colocate one starter descriptor, renderer, and resource package."""

    info: ProviderStarter
    package: str
    render: Callable[[StarterContext], StarterRendering]


StarterCatalog = Mapping[str, BundledStarter]

_MARKER_NAME = re.compile(r"__[A-Z0-9_]+__")
_LINE_SEPARATOR = re.compile(r"\r\n|\r|\n")


def starter_catalog(*starters: BundledStarter) -> StarterCatalog:
    """Index bundled starters by their provider-local keys."""
    records: dict[str, BundledStarter] = {}
    for starter in starters:
        if starter.info.key in records:
            raise ValueError(f"Duplicate bundled starter {starter.info.key!r}")
        records[starter.info.key] = starter
    return MappingProxyType(records)


def provider_starters(catalog: StarterCatalog) -> tuple[ProviderStarter, ...]:
    """Return the public records from one bundled starter catalog."""
    return tuple(starter.info for starter in catalog.values())


def notebook_label(context: StarterContext) -> str:
    """Return the notebook's app title, or a readable form of its filename."""
    configured = context.notebook.app_config.get("app_title")
    if isinstance(configured, str) and configured.strip():
        return configured.strip()
    words = context.notebook_name.replace("_", " ").replace("-", " ").split()
    return " ".join(words).title()


def _replacements(
    context: StarterContext,
    additions: Mapping[str, str],
) -> dict[str, str]:
    heading = context.view_name.replace("-", " ").title()
    label = notebook_label(context)
    replacements = {
        "__NOTEBOOK_LABEL_HTML__": html.escape(label),
        "__VIEW_HEADING_HTML__": html.escape(heading),
        "__NOTEBOOK_LABEL_JSON__": json.dumps(label),
        "__VIEW_HEADING_JSON__": json.dumps(heading),
    }
    for marker, value in additions.items():
        if _MARKER_NAME.fullmatch(marker) is None:
            raise ValueError(f"Invalid bundled starter marker {marker!r}")
        if marker in replacements:
            raise ValueError(f"Duplicate bundled starter marker {marker!r}")
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

            rendered = marker_pattern.sub(
                replacement,
                source,
            )
            files[relative] = rendered.encode()

    visit(root, PurePosixPath())
    return files


def _starter_files(
    starter: BundledStarter,
    requested: ProviderStarter,
    context: StarterContext,
    replacements: Mapping[str, str],
) -> dict[PurePosixPath, bytes]:
    """Render one bundled starter from provider-wide and starter-specific files."""
    selected = resources.files(starter.package).joinpath("files")
    if not selected.is_dir():
        raise ValueError(
            f"Bundled starter {requested.key!r} is missing files in {starter.package!r}"
        )

    rendered_values = _replacements(context, replacements)
    marker_pattern = re.compile(
        "|".join(
            re.escape(marker)
            for marker in sorted(rendered_values, key=len, reverse=True)
        )
    )
    files = _tree_files(
        selected,
        rendered_values,
        marker_pattern,
    )

    missing = sorted(set(requested.documents) - files.keys())
    if missing:
        raise ValueError(
            f"Bundled starter {requested.key!r} is missing {missing[0].as_posix()!r}"
        )
    return dict(sorted(files.items(), key=lambda item: item[0].as_posix()))


def create_starter(
    catalog: StarterCatalog,
    requested: ProviderStarter,
    context: StarterContext,
) -> StarterPlan:
    """Create one provider plan through its registered leaf renderer."""
    starter = catalog.get(requested.key)
    if starter is None:
        raise ValueError(f"Unknown bundled starter {requested.key!r}")
    if starter.info != requested:
        raise ValueError(
            f"Bundled starter {requested.key!r} does not match its catalog"
        )
    rendering = starter.render(context)
    return StarterPlan(
        files=_starter_files(
            starter,
            requested,
            context,
            rendering.replacements,
        ),
        cell_targets=rendering.cell_targets,
    )


def starter_cells(
    context: StarterContext,
) -> tuple[tuple[CellSpec, StarterCellTarget], ...]:
    """Return transitively enabled cells and their generated source targets."""
    cells = context.notebook.by_ref()
    disabled = {cell.ref for cell in context.notebook.cells if cell.config.disabled}
    pending = list(disabled)
    while pending:
        ref = pending.pop()
        for child in cells[ref].downstream:
            if child in disabled:
                continue
            disabled.add(child)
            pending.append(child)
    return tuple(
        (cell, context.cell_targets[cell.ref])
        for cell in context.notebook.cells
        if cell.kind == "cell" and cell.ref not in disabled
    )


def typescript_string_array(
    values: tuple[str, ...],
    *,
    indent: str = "",
) -> str:
    """Render strings in the stable multiline form accepted by Deno fmt."""
    items = "".join(
        f"{indent}  {json.dumps(value, ensure_ascii=False)},\n" for value in values
    )
    return f"[\n{items}{indent}]"
