"""Saved notebook and live-cell identity records."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from marimo_studio._projections.runtime_records import RuntimeProbe
from marimo_studio.errors import CapabilityInputError


@dataclass(frozen=True, order=True)
class CellRef:
    fingerprint: str
    layout_fingerprint: str
    occurrence: int = 0

    PREFIX = "cell:v1:"

    def __post_init__(self) -> None:
        fingerprint = self._digest(self.fingerprint)
        layout_fingerprint = self._digest(self.layout_fingerprint)
        if self.occurrence < 0:
            raise ValueError("Cell reference occurrence must be non-negative")
        object.__setattr__(self, "fingerprint", fingerprint)
        object.__setattr__(self, "layout_fingerprint", layout_fingerprint)

    @staticmethod
    def _digest(value: str) -> str:
        digest = value.lower()
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("Cell references require full SHA-256 digests")
        return digest

    @classmethod
    def parse(cls, value: CellRef | str) -> CellRef:
        if isinstance(value, cls):
            return value
        if not isinstance(value, str):
            raise TypeError("Cell reference must be a string or CellRef")
        if not value.startswith(cls.PREFIX):
            raise ValueError(f"Invalid cell reference: {value}")
        payload, separator, occurrence = value.removeprefix(cls.PREFIX).rpartition(":")
        fingerprint, digest_separator, layout_fingerprint = payload.partition(":")
        if not separator or not digest_separator:
            raise ValueError(f"Invalid cell reference: {value}")
        try:
            occurrence_index = int(occurrence)
        except ValueError as error:
            raise ValueError(f"Invalid cell reference occurrence: {value}") from error
        return cls(fingerprint, layout_fingerprint, occurrence_index)

    def __str__(self) -> str:
        return (
            f"{self.PREFIX}{self.fingerprint}:{self.layout_fingerprint}:"
            f"{self.occurrence}"
        )


CellSelector = CellRef | str | int


@dataclass(frozen=True)
class LiveCellIdentity:
    ref: CellRef
    runtime_id: str


@dataclass(frozen=True)
class LiveCellSnapshot:
    ids: Mapping[CellRef, str]
    names: Mapping[str, tuple[LiveCellIdentity, ...]]
    dependency_closures: Mapping[str, tuple[str, ...]]
    current_refs: Mapping[str, CellRef]


@dataclass(frozen=True)
class SourceSpan:
    start_line: int
    end_line: int
    start_column: int = 0
    end_column: int = 0


@dataclass(frozen=True)
class CellConfigSpec:
    column: int | None
    disabled: bool
    hide_code: bool


@dataclass(frozen=True)
class CellSpec:
    ref: CellRef
    runtime_id: str
    index: int
    name: str | None
    source: SourceSpan
    code_sha256: str
    preview: str
    definitions: tuple[str, ...]
    references: tuple[str, ...]
    upstream: tuple[CellRef, ...]
    downstream: tuple[CellRef, ...]
    config: CellConfigSpec
    has_output_expression: bool
    code: str | None = None

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["ref"] = str(self.ref)
        value["definitions"] = list(self.definitions)
        value["references"] = list(self.references)
        value["upstream"] = [str(ref) for ref in self.upstream]
        value["downstream"] = [str(ref) for ref in self.downstream]
        if self.code is None:
            value.pop("code")
        return value


@dataclass(frozen=True)
class NotebookSpec:
    path: Path
    cells: tuple[CellSpec, ...]
    app_config: dict[str, Any]

    def by_ref(self) -> dict[CellRef, CellSpec]:
        return {cell.ref: cell for cell in self.cells}

    def named_cells(self) -> dict[str, CellSpec]:
        return {cell.name: cell for cell in self.cells if cell.name is not None}

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": 1,
            "notebook": str(self.path),
            "app_config": self.app_config,
            "cells": [cell.to_dict() for cell in self.cells],
        }


def select_cells(
    notebook: NotebookSpec,
    *,
    selectors: Sequence[CellSelector] = (),
    output_expressions: bool = False,
    limit: int | None = None,
) -> tuple[CellSpec, ...]:
    """Select notebook cells for an inspection result."""
    if limit is not None and (
        not isinstance(limit, int) or isinstance(limit, bool) or limit < 1
    ):
        raise CapabilityInputError(
            "invalid-inspection-request",
            "limit",
            "limit must be an integer greater than or equal to 1",
        )
    if isinstance(selectors, (str, bytes)):
        raise CapabilityInputError(
            "invalid-inspection-request",
            "selectors",
            "selectors must be a sequence of cell refs, names, or indices",
        )
    selected_refs: set[CellRef] | None = None
    if selectors:
        by_ref = notebook.by_ref()
        by_name = notebook.named_cells()
        by_index = {cell.index: cell for cell in notebook.cells}
        selected_refs = set()
        for selector in selectors:
            selected: CellSpec | None
            if isinstance(selector, CellRef):
                selected = by_ref.get(selector)
            elif type(selector) is int:
                selected = by_index.get(selector)
            elif isinstance(selector, str):
                if selector.startswith(CellRef.PREFIX):
                    try:
                        selected = by_ref.get(CellRef.parse(selector))
                    except ValueError:
                        selected = None
                else:
                    selected = by_name.get(selector)
            else:
                selected = None
            if selected is None:
                raise CapabilityInputError(
                    "invalid-inspection-request",
                    "selectors",
                    f"Unknown cell selector: {selector!r}",
                )
            selected_refs.add(selected.ref)
    cells = tuple(
        cell
        for cell in notebook.cells
        if (selected_refs is None or cell.ref in selected_refs)
        and (not output_expressions or cell.has_output_expression)
    )
    return cells if limit is None else cells[:limit]


@dataclass(frozen=True)
class InspectionResult:
    """Selected notebook cells with optional runtime evidence."""

    notebook: NotebookSpec
    cells: tuple[CellSpec, ...]
    runtime: RuntimeProbe | None = None

    def to_dict(self) -> dict[str, object]:
        payload = self.notebook.to_dict()
        if self.runtime is None:
            payload["cells"] = [cell.to_dict() for cell in self.cells]
            return payload
        payload["cells"] = [
            {
                **cell.to_dict(),
                "runtime": self.runtime.cells[cell.runtime_id].to_dict(),
            }
            for cell in self.cells
        ]
        payload["runtime"] = self.runtime.values.to_dict()
        return payload
