"""Build the symbolic notebook graph used by every view projection."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from marimo_studio._notebook.records import CellRef, CellSpec, NotebookSpec, SourceSpan


@dataclass(frozen=True)
class NotebookCellSymbol:
    """Describe one notebook cell without binding it to a live runtime ID."""

    ref: CellRef
    index: int
    name: str | None
    aliases: tuple[str, ...]
    source: SourceSpan
    definitions: tuple[str, ...]
    references: tuple[str, ...]
    upstream: tuple[CellRef, ...]
    downstream: tuple[CellRef, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "index": self.index,
            "name": self.name,
            "aliases": list(self.aliases),
            "source": {
                "startLine": self.source.start_line,
                "endLine": self.source.end_line,
                "startColumn": self.source.start_column,
                "endColumn": self.source.end_column,
            },
            "definitions": list(self.definitions),
            "references": list(self.references),
            "upstream": [str(ref) for ref in self.upstream],
            "downstream": [str(ref) for ref in self.downstream],
        }


@dataclass(frozen=True)
class NotebookVariableSymbol:
    """Record every producer and consumer of one notebook variable."""

    name: str
    producers: tuple[CellRef, ...]
    consumers: tuple[CellRef, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "producers": [str(ref) for ref in self.producers],
            "consumers": [str(ref) for ref in self.consumers],
        }


@dataclass(frozen=True)
class NotebookSymbolGraph:
    """Finite notebook symbols and dependency edges for one source revision."""

    revision: str
    cells: dict[CellRef, NotebookCellSymbol]
    cell_targets: dict[str, tuple[CellRef, ...]]
    variables: dict[str, NotebookVariableSymbol]

    def dependency_closure(self, producer: CellRef) -> tuple[CellRef, ...]:
        """Return upstream cells and ``producer`` in notebook order."""
        if producer not in self.cells:
            raise KeyError(producer)
        required: set[CellRef] = set()
        pending = [producer]
        while pending:
            current = pending.pop()
            if current in required:
                continue
            required.add(current)
            pending.extend(self.cells[current].upstream)
        return tuple(ref for ref in self.cells if ref in required)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": 1,
            "revision": self.revision,
            "cells": {str(ref): symbol.to_dict() for ref, symbol in self.cells.items()},
            "cellTargets": {
                target: [str(ref) for ref in refs]
                for target, refs in sorted(self.cell_targets.items())
            },
            "variables": {
                name: symbol.to_dict()
                for name, symbol in sorted(self.variables.items())
            },
        }


def _append_unique(mapping: dict[str, list[CellRef]], key: str, ref: CellRef) -> None:
    values = mapping.setdefault(key, [])
    if ref not in values:
        values.append(ref)


def build_notebook_symbol_graph(
    notebook: NotebookSpec,
    aliases: dict[str, CellSpec],
) -> NotebookSymbolGraph:
    """Build a revisioned graph from static notebook inspection and cell aliases."""
    target_refs: dict[str, list[CellRef]] = {}
    aliases_by_ref: dict[CellRef, list[str]] = {}
    for cell in notebook.cells:
        if cell.name is not None:
            _append_unique(target_refs, cell.name, cell.ref)
    for alias, cell in sorted(aliases.items()):
        _append_unique(target_refs, alias, cell.ref)
        if alias != cell.name:
            aliases_by_ref.setdefault(cell.ref, []).append(alias)

    producers: dict[str, list[CellRef]] = {}
    consumers: dict[str, list[CellRef]] = {}
    cells: dict[CellRef, NotebookCellSymbol] = {}
    for cell in notebook.cells:
        for definition in cell.definitions:
            _append_unique(producers, definition, cell.ref)
        for reference in cell.references:
            _append_unique(consumers, reference, cell.ref)
        cells[cell.ref] = NotebookCellSymbol(
            ref=cell.ref,
            index=cell.index,
            name=cell.name,
            aliases=tuple(sorted(aliases_by_ref.get(cell.ref, ()))),
            source=cell.source,
            definitions=cell.definitions,
            references=cell.references,
            upstream=cell.upstream,
            downstream=cell.downstream,
        )

    variables = {
        name: NotebookVariableSymbol(
            name=name,
            producers=tuple(producers.get(name, ())),
            consumers=tuple(consumers.get(name, ())),
        )
        for name in sorted(set(producers).union(consumers))
    }
    cell_targets = {target: tuple(refs) for target, refs in sorted(target_refs.items())}
    identity = {
        "cells": {str(ref): symbol.to_dict() for ref, symbol in cells.items()},
        "cellTargets": {
            target: [str(ref) for ref in refs] for target, refs in cell_targets.items()
        },
        "variables": {name: symbol.to_dict() for name, symbol in variables.items()},
    }
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    return NotebookSymbolGraph(
        revision=f"sha256:{hashlib.sha256(encoded).hexdigest()}",
        cells=cells,
        cell_targets=cell_targets,
        variables=variables,
    )
