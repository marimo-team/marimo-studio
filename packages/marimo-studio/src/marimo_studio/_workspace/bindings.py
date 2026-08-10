"""Resolve and edit notebook-level cell aliases."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, MutableMapping
from dataclasses import dataclass
from typing import Any

import tomlkit

from marimo_studio._cell_refs import cell_ref_candidates, safe_cell_ref_matches
from marimo_studio._workspace.config import editable_studio_config
from marimo_studio._workspace.files import atomic_write_text, reject_mutable_symlinks
from marimo_studio._workspace.metadata import (
    set_cell_bindings,
    update_notebook_config,
)
from marimo_studio._workspace.models import (
    ALIAS_PATTERN,
    BindingResult,
    ProjectionDiagnostic,
    ProjectionKind,
    ResolvedStudio,
    ResolvedView,
    StudioWorkspace,
    View,
)
from marimo_studio._workspace.ports import NotebookInspector
from marimo_studio._workspace.templates import (
    TemplateParser,
    validate_template_structure,
)
from marimo_studio.errors import BindingError, ConfigurationError, TemplateError
from marimo_studio.types import CellRef, CellSpec, ValueBinding
from marimo_studio.values import MAX_OUTPUT_SELECTORS


@dataclass(frozen=True)
class _AliasFailure:
    code: str
    message: str
    hint: str


def _projection_position(
    parser: TemplateParser,
    projection: ProjectionKind,
    target: str,
) -> tuple[int, int]:
    if projection == "value":
        return parser.value_positions.get(target, (1, 1))
    if projection == "output":
        return parser.output_positions.get(target, (1, 1))
    return parser.alias_positions.get(
        target,
        parser.fragment_alias_positions.get(target, (1, 1)),
    )


def _diagnostic(
    view: View,
    parser: TemplateParser,
    *,
    code: str,
    message: str,
    hint: str,
    projection: ProjectionKind,
    target: str,
) -> ProjectionDiagnostic:
    line, column = _projection_position(parser, projection, target)
    return ProjectionDiagnostic(
        code=code,
        severity="error",
        message=message,
        hint=hint,
        view=view.name,
        projection=projection,
        target=target,
        source=view.template,
        line=line,
        column=column,
    )


def _resolve_view(
    view: View,
    aliases: dict[str, CellSpec],
    defining_cells: dict[str, list[CellSpec]],
    alias_failures: dict[str, _AliasFailure],
    document: str | None = None,
) -> ResolvedView:
    parser = TemplateParser()
    try:
        parser.feed(
            document
            if document is not None
            else view.template.read_text(encoding="utf-8")
        )
    except TemplateError as error:
        raise error.with_source(view.template) from error
    except Exception as error:
        raise TemplateError(
            f"Could not parse {view.template}: {error}",
            source=view.template,
        ) from error
    validate_template_structure(parser, view.template)
    if parser.projection_outside_shell:
        raise TemplateError(
            f"{view.template}: projection hosts must be inside #app-shell",
            source=view.template,
        )
    if parser.has_reserved_runtime_markup:
        raise TemplateError(
            f"{view.template}: template contains reserved runtime markup",
            source=view.template,
        )
    duplicates = sorted(
        alias for alias in set(parser.aliases) if parser.aliases.count(alias) > 1
    )
    if duplicates:
        line, column = parser.alias_positions[duplicates[0]]
        raise TemplateError(
            f"{view.template}: a cell alias may appear once: " + ", ".join(duplicates),
            source=view.template,
            line=line,
            column=column,
        )
    duplicate_outputs = sorted(
        source
        for source in set(reference.source for reference in parser.output_references)
        if sum(reference.source == source for reference in parser.output_references) > 1
    )
    if duplicate_outputs:
        line, column = parser.output_positions[duplicate_outputs[0]]
        raise TemplateError(
            f"{view.template}: an output selector may appear once: "
            + ", ".join(duplicate_outputs),
            source=view.template,
            line=line,
            column=column,
        )
    if len(parser.output_references) > MAX_OUTPUT_SELECTORS:
        first_excess = parser.output_references[MAX_OUTPUT_SELECTORS]
        line, column = parser.output_positions[first_excess.source]
        raise TemplateError(
            f"{view.template}: a view may contain at most "
            f"{MAX_OUTPUT_SELECTORS} output selectors",
            source=view.template,
            line=line,
            column=column,
        )
    projected_aliases = tuple(
        dict.fromkeys((*parser.aliases, *parser.fragment_aliases))
    )
    diagnostics: list[ProjectionDiagnostic] = []
    for alias in projected_aliases:
        if alias in aliases:
            continue
        failure = alias_failures.get(alias)
        diagnostics.append(
            _diagnostic(
                view,
                parser,
                code=failure.code if failure else "cell-not-found",
                message=(
                    failure.message
                    if failure
                    else f"Cell {alias!r} is not defined in the notebook."
                ),
                hint=(
                    failure.hint
                    if failure
                    else "Name a notebook cell, change the projection target, "
                    "or remove it from the view."
                ),
                projection="cell",
                target=alias,
            )
        )
    value_bindings: dict[str, ValueBinding] = {}
    references = {reference.source: reference for reference in parser.value_references}
    for source, reference in references.items():
        defining = defining_cells.get(reference.variable, [])
        if not defining:
            diagnostics.append(
                _diagnostic(
                    view,
                    parser,
                    code="value-variable-not-found",
                    message=(
                        f"Value {source!r} depends on notebook variable "
                        f"{reference.variable!r}, which has no defining cell."
                    ),
                    hint="Define the variable, change the selector, or remove "
                    "the value projection from the view.",
                    projection="value",
                    target=source,
                )
            )
            continue
        if len(defining) > 1:
            diagnostics.append(
                _diagnostic(
                    view,
                    parser,
                    code="value-variable-ambiguous",
                    message=(
                        f"Value {source!r} depends on notebook variable "
                        f"{reference.variable!r}, which has multiple defining cells."
                    ),
                    hint="Give the variable one defining cell before projecting it.",
                    projection="value",
                    target=source,
                )
            )
            continue
        line, column = parser.value_positions[source]
        value_bindings[source] = ValueBinding(
            reference=reference,
            cell=defining[0],
            source=view.template,
            line=line,
            column=column,
        )
    output_bindings: dict[str, ValueBinding] = {}
    output_references = {
        reference.source: reference for reference in parser.output_references
    }
    for source, reference in output_references.items():
        defining = defining_cells.get(reference.variable, [])
        if not defining:
            diagnostics.append(
                _diagnostic(
                    view,
                    parser,
                    code="output-variable-not-found",
                    message=(
                        f"Output {source!r} depends on notebook variable "
                        f"{reference.variable!r}, which has no defining cell."
                    ),
                    hint="Define the variable, change the selector, or remove "
                    "the output projection from the view.",
                    projection="output",
                    target=source,
                )
            )
            continue
        if len(defining) > 1:
            diagnostics.append(
                _diagnostic(
                    view,
                    parser,
                    code="output-variable-ambiguous",
                    message=(
                        f"Output {source!r} depends on notebook variable "
                        f"{reference.variable!r}, which has multiple defining cells."
                    ),
                    hint="Give the variable one defining cell before projecting it.",
                    projection="output",
                    target=source,
                )
            )
            continue
        line, column = parser.output_positions[source]
        output_bindings[source] = ValueBinding(
            reference=reference,
            cell=defining[0],
            source=view.template,
            line=line,
            column=column,
        )
    return ResolvedView(
        view=view,
        cell_aliases=projected_aliases,
        value_bindings=value_bindings,
        output_bindings=output_bindings,
        diagnostics=tuple(diagnostics),
    )


def _resolve_aliases(
    studio: StudioWorkspace,
    notebook_cells: tuple[CellSpec, ...],
    native_aliases: dict[str, CellSpec],
) -> tuple[dict[str, CellSpec], dict[str, _AliasFailure]]:
    aliases = dict(native_aliases)
    failures: dict[str, _AliasFailure] = {}
    cells_by_id = {cell.runtime_id: cell for cell in notebook_cells}
    resolved_ids = safe_cell_ref_matches(
        studio.cells,
        ((cell.ref, cell.runtime_id) for cell in notebook_cells),
    )
    for alias, ref in studio.cells.items():
        native = aliases.get(alias)
        matches = cell_ref_candidates(
            ref,
            ((cell.ref, cell) for cell in notebook_cells),
        )
        cell = cells_by_id.get(resolved_ids.get(alias, ""))
        if cell is None and matches:
            if native is not None:
                continue
            message = (
                f"Cell alias {alias!r} matches more than one notebook cell."
                if len(matches) > 1
                else f"Cell alias {alias!r} conflicts with another cell binding."
            )
            failures[alias] = _AliasFailure(
                "cell-binding-ambiguous",
                message,
                "Inspect the notebook, then bind this alias again with --overwrite.",
            )
            aliases.pop(alias, None)
            continue
        if cell is None:
            if native is not None:
                continue
            failures[alias] = _AliasFailure(
                "cell-binding-stale",
                f"Cell alias {alias!r} does not match a notebook cell.",
                "Inspect the notebook, then bind this alias again with --overwrite.",
            )
            aliases.pop(alias, None)
            continue
        if native is not None and native.runtime_id != cell.runtime_id:
            failures[alias] = _AliasFailure(
                "cell-binding-conflict",
                f"Cell alias {alias!r} conflicts with a named notebook cell.",
                "Rename the notebook cell or choose a different configured alias.",
            )
            aliases.pop(alias, None)
            continue
        aliases[alias] = cell
    return aliases, failures


def resolve_studio(
    studio: StudioWorkspace,
    *,
    inspect_notebook: NotebookInspector,
    include_code: bool = False,
    view_name: str | None = None,
    view_documents: Mapping[str, str] | None = None,
) -> ResolvedStudio:
    """Resolve configured view templates against the current notebook graph."""
    if not studio.notebook.is_file():
        raise ConfigurationError(f"Notebook does not exist: {studio.notebook}")
    notebook = inspect_notebook(studio.notebook, include_code=include_code)
    aliases, alias_failures = _resolve_aliases(
        studio,
        notebook.cells,
        notebook.named_cells(),
    )

    defining_cells: dict[str, list[CellSpec]] = {}
    for cell in notebook.cells:
        for definition in cell.definitions:
            defining_cells.setdefault(definition, []).append(cell)
    if view_name is not None and view_name not in studio.views:
        available = ", ".join(studio.views)
        raise ConfigurationError(
            f"Unknown view {view_name!r}. Available views: {available}."
        )
    selected_views = (
        {view_name: studio.views[view_name]} if view_name is not None else studio.views
    )
    resolved_views = {
        name: _resolve_view(
            view,
            aliases,
            defining_cells,
            alias_failures,
            None if view_documents is None else view_documents.get(name),
        )
        for name, view in selected_views.items()
    }
    return ResolvedStudio(studio, notebook, aliases, resolved_views)


def bind_cell(
    studio: StudioWorkspace,
    alias: str,
    cell_index: int,
    *,
    inspect_notebook: NotebookInspector,
    dry_run: bool = False,
    overwrite: bool = False,
) -> BindingResult:
    """Bind a stable alias to a notebook cell."""
    if not ALIAS_PATTERN.fullmatch(alias):
        raise ConfigurationError(f"Invalid cell alias: {alias}")
    notebook = inspect_notebook(studio.notebook)
    try:
        cell = notebook.cells[cell_index]
    except IndexError as error:
        raise BindingError(
            f"Cell index {cell_index} is outside 0-{len(notebook.cells) - 1}"
        ) from error
    native = notebook.named_cells().get(alias)
    if native is not None and native.ref != cell.ref:
        raise BindingError(f"Alias {alias!r} conflicts with the named notebook cell")
    previous_ref = studio.cells.get(alias)
    if previous_ref is not None and previous_ref != cell.ref and not overwrite:
        raise BindingError(
            f"Alias {alias!r} already points to {previous_ref}. "
            "Pass --overwrite to replace it."
        )
    result = BindingResult(alias, cell, studio.config_path, previous_ref)
    if dry_run:
        return result
    _write_cell_bindings(studio, {alias: cell.ref})
    return result


def _write_cell_bindings(
    studio: StudioWorkspace,
    bindings: Mapping[str, CellRef],
    *,
    remove: Iterable[str] = (),
) -> None:
    """Persist cell bindings through the workspace configuration owner."""
    removed = tuple(remove)
    if studio.uses_notebook_config:
        reject_mutable_symlinks(studio.notebook.parent, {studio.notebook})

        def update(config: MutableMapping[str, Any]) -> None:
            set_cell_bindings(config, bindings, remove=removed)

        update_notebook_config(studio.notebook, update)
    else:
        reject_mutable_symlinks(studio.root, {studio.config_path})
        document = tomlkit.parse(studio.config_path.read_text(encoding="utf-8"))
        config = editable_studio_config(document)
        set_cell_bindings(config, bindings, remove=removed)
        atomic_write_text(studio.config_path, tomlkit.dumps(document))
