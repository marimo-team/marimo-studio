"""Resolve and edit notebook-level cell aliases."""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any

import tomlkit

from marimo_studio._workspace.config import (
    TemplateParser,
    editable_studio_config,
    validate_template_structure,
)
from marimo_studio._workspace.files import atomic_write_text, reject_mutable_symlinks
from marimo_studio._workspace.metadata import update_notebook_config
from marimo_studio._workspace.models import (
    ALIAS_PATTERN,
    BindingResult,
    ResolvedStudio,
    ResolvedView,
    StudioConfig,
    View,
)
from marimo_studio.errors import BindingError, ConfigurationError
from marimo_studio.inspect import inspect_notebook
from marimo_studio.types import CellSpec, ValueBinding


def _resolve_view(
    view: View,
    aliases: dict[str, CellSpec],
    defining_cells: dict[str, list[CellSpec]],
) -> ResolvedView:
    parser = TemplateParser()
    try:
        parser.feed(view.template.read_text(encoding="utf-8"))
    except ConfigurationError as error:
        raise ConfigurationError(f"{view.template}: {error}") from error
    except Exception as error:
        raise ConfigurationError(f"Could not parse {view.template}: {error}") from error
    validate_template_structure(parser, view.template)
    if parser.projection_outside_shell:
        raise ConfigurationError(
            f"{view.template}: cell and value hosts must be inside #app-shell"
        )
    if parser.has_reserved_runtime_markup:
        raise ConfigurationError(
            f"{view.template}: template contains reserved runtime markup"
        )
    duplicates = sorted(
        alias for alias in set(parser.aliases) if parser.aliases.count(alias) > 1
    )
    if duplicates:
        raise ConfigurationError(
            f"{view.template}: a cell alias may appear once: " + ", ".join(duplicates)
        )
    projected_aliases = tuple(
        dict.fromkeys((*parser.aliases, *parser.fragment_aliases))
    )
    unknown = sorted(set(projected_aliases).difference(aliases))
    if unknown:
        raise BindingError(
            f"{view.template}: unbound cell aliases: {', '.join(unknown)}. "
            "Add them to [tool.marimo-studio.cells]."
        )
    unknown_variables = sorted(
        {
            reference.variable
            for reference in parser.value_references
            if reference.variable not in defining_cells
        }
    )
    if unknown_variables:
        raise BindingError(
            f"{view.template}: undefined notebook variables: "
            + ", ".join(unknown_variables)
        )
    ambiguous_variables = sorted(
        {
            reference.variable
            for reference in parser.value_references
            if len(defining_cells[reference.variable]) != 1
        }
    )
    if ambiguous_variables:
        raise BindingError(
            f"{view.template}: variables have multiple defining cells: "
            + ", ".join(ambiguous_variables)
        )
    value_bindings = {
        reference.source: ValueBinding(
            reference=reference,
            cell=defining_cells[reference.variable][0],
        )
        for reference in parser.value_references
    }
    return ResolvedView(
        view=view,
        cell_aliases=projected_aliases,
        value_bindings=value_bindings,
    )


def resolve_studio(
    studio: StudioConfig,
    *,
    include_code: bool = False,
    view_name: str | None = None,
) -> ResolvedStudio:
    """Resolve configured view templates against the current notebook graph."""
    if not studio.notebook.is_file():
        raise ConfigurationError(f"Notebook does not exist: {studio.notebook}")
    notebook = inspect_notebook(studio.notebook, include_code=include_code)
    aliases = notebook.named_cells()
    for alias, ref in studio.cells.items():
        semantic_matches = [
            cell
            for cell in notebook.cells
            if cell.ref.fingerprint == ref.fingerprint
            and cell.ref.occurrence == ref.occurrence
        ]
        if semantic_matches:
            cell = semantic_matches[0]
        else:
            layout_matches = [
                cell
                for cell in notebook.cells
                if cell.ref.layout_fingerprint == ref.layout_fingerprint
            ]
            if len(layout_matches) > 1:
                raise BindingError(
                    f"Binding {alias!r} became ambiguous after notebook "
                    "serialization. Inspect the notebook and bind the alias "
                    "again with --overwrite."
                )
            cell = layout_matches[0] if layout_matches else None
        if cell is None:
            raise BindingError(
                f"Binding {alias!r} points to changed or missing cell {ref}. "
                "Inspect the notebook and bind the alias again with --overwrite."
            )
        native = aliases.get(alias)
        if native is not None and native.runtime_id != cell.runtime_id:
            raise BindingError(
                f"Binding {alias!r} conflicts with a named notebook cell"
            )
        aliases[alias] = cell

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
        name: _resolve_view(view, aliases, defining_cells)
        for name, view in selected_views.items()
    }
    return ResolvedStudio(studio, notebook, aliases, resolved_views)


def binding_value(cell: CellSpec) -> Any:
    value = tomlkit.inline_table()
    value["ref"] = str(cell.ref)
    return value


def bind_cell(
    studio: StudioConfig,
    alias: str,
    cell_index: int,
    *,
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
    if studio.uses_notebook_config:
        reject_mutable_symlinks(studio.notebook.parent, {studio.notebook})

        def update(config: MutableMapping[str, Any]) -> None:
            cells = config.setdefault("cells", tomlkit.table())
            if not isinstance(cells, MutableMapping):
                raise ConfigurationError("cells must be a TOML table")
            cells[alias] = binding_value(cell)

        update_notebook_config(studio.notebook, update)
    else:
        reject_mutable_symlinks(studio.root, {studio.config_path})
        document = tomlkit.parse(studio.config_path.read_text(encoding="utf-8"))
        config = editable_studio_config(document)
        cells = config.setdefault("cells", tomlkit.table())
        if not isinstance(cells, MutableMapping):
            raise ConfigurationError("cells must be a TOML table")
        cells[alias] = binding_value(cell)
        atomic_write_text(studio.config_path, tomlkit.dumps(document))
    return result
