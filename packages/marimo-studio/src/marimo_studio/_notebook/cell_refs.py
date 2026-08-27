"""Build stable cell references from notebook source."""

from __future__ import annotations

import ast
import hashlib
import textwrap
from collections import Counter
from collections.abc import Iterable, Mapping
from typing import TypeVar

from marimo_studio._notebook.records import CellRef

_T = TypeVar("_T")


def _is_marimo_markdown_call(value: ast.Call) -> bool:
    return (
        isinstance(value.func, ast.Attribute)
        and isinstance(value.func.value, ast.Name)
        and value.func.value.id == "mo"
        and value.func.attr == "md"
        and bool(value.args)
    )


def _canonical_ast(
    value: object,
    *,
    normalize_marimo_layout: bool = False,
    normalize_markdown_text: bool = False,
) -> object:
    if normalize_markdown_text and isinstance(value, ast.JoinedStr):
        expressions: list[object] = []
        template = ""
        for child in value.values:
            if isinstance(child, ast.Constant) and isinstance(child.value, str):
                template += child.value
            else:
                marker = f"\0{len(expressions)}\0"
                template += marker
                expressions.append(
                    _canonical_ast(
                        child,
                        normalize_marimo_layout=normalize_marimo_layout,
                    )
                )
        return (
            "JoinedStr",
            textwrap.dedent(template).strip("\n"),
            tuple(expressions),
        )
    if isinstance(value, ast.AST):
        fields: list[tuple[str, object]] = []
        for name, child in ast.iter_fields(value):
            if child is None or child == []:
                continue
            normalize_child_text = normalize_markdown_text
            if (
                normalize_marimo_layout
                and isinstance(value, ast.Call)
                and name == "args"
                and _is_marimo_markdown_call(value)
            ):
                arguments = list(child)
                child = [
                    _canonical_ast(
                        argument,
                        normalize_marimo_layout=True,
                        normalize_markdown_text=index == 0,
                    )
                    for index, argument in enumerate(arguments)
                ]
                normalize_child_text = False
            if (
                normalize_markdown_text
                and isinstance(value, ast.Constant)
                and name == "value"
                and isinstance(child, str)
                and "\n" in child
            ):
                child = textwrap.dedent(child).strip("\n")
            fields.append(
                (
                    name,
                    _canonical_ast(
                        child,
                        normalize_marimo_layout=normalize_marimo_layout,
                        normalize_markdown_text=normalize_child_text,
                    ),
                )
            )
        return type(value).__name__, tuple(fields)
    if isinstance(value, list):
        return tuple(
            _canonical_ast(
                item,
                normalize_marimo_layout=normalize_marimo_layout,
                normalize_markdown_text=normalize_markdown_text,
            )
            for item in value
        )
    return value


def _ast_fingerprint(code: str, *, normalize_marimo_layout: bool) -> str:
    try:
        payload = repr(
            _canonical_ast(
                ast.parse(code),
                normalize_marimo_layout=normalize_marimo_layout,
            )
        ).encode("utf-8")
    except SyntaxError:
        payload = code.strip().encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _cell_fingerprint(code: str) -> str:
    return _ast_fingerprint(code, normalize_marimo_layout=False)


def _layout_fingerprint(code: str) -> str:
    return _ast_fingerprint(code, normalize_marimo_layout=True)


def cell_refs(codes: Iterable[str]) -> tuple[CellRef, ...]:
    """Return semantic references in document order."""
    occurrences: Counter[str] = Counter()
    refs: list[CellRef] = []
    for code in codes:
        fingerprint = _cell_fingerprint(code)
        layout_fingerprint = _layout_fingerprint(code)
        refs.append(
            CellRef(
                fingerprint,
                layout_fingerprint,
                occurrences[fingerprint],
            )
        )
        occurrences[fingerprint] += 1
    return tuple(refs)


def cell_ref_candidates(
    ref: CellRef,
    candidates: Iterable[tuple[CellRef, _T]],
) -> tuple[_T, ...]:
    """Return the semantic match or every layout-equivalent candidate."""
    available = tuple(candidates)
    semantic = tuple(
        value
        for candidate, value in available
        if candidate.fingerprint == ref.fingerprint
        and candidate.occurrence == ref.occurrence
    )
    if semantic:
        return semantic
    return tuple(
        value
        for candidate, value in available
        if candidate.layout_fingerprint == ref.layout_fingerprint
    )


def safe_cell_ref_matches(
    bindings: Mapping[str, CellRef],
    candidates: Iterable[tuple[CellRef, str]],
) -> dict[str, str]:
    """Return unique matches that preserve distinct configured bindings."""
    available = tuple(candidates)
    resolved = {
        alias: matches[0]
        for alias, ref in bindings.items()
        if len(matches := cell_ref_candidates(ref, available)) == 1
    }
    aliases_by_id: dict[str, list[str]] = {}
    for alias, runtime_id in resolved.items():
        aliases_by_id.setdefault(runtime_id, []).append(alias)
    for aliases in aliases_by_id.values():
        if len({bindings[alias] for alias in aliases}) > 1:
            for alias in aliases:
                resolved.pop(alias)
    return resolved


def safe_cell_ref_updates(
    bindings: Mapping[str, CellRef],
    updates: Mapping[str, CellRef],
) -> dict[str, CellRef]:
    """Return automatic updates that keep distinct bindings distinct."""
    accepted = dict(updates)
    while True:
        effective = dict(bindings)
        effective.update(accepted)
        aliases_by_ref: dict[CellRef, list[str]] = {}
        for alias, ref in effective.items():
            aliases_by_ref.setdefault(ref, []).append(alias)

        blocked: set[str] = set()
        for aliases in aliases_by_ref.values():
            original_refs = {bindings[alias] for alias in aliases if alias in bindings}
            if len(original_refs) > 1:
                blocked.update(
                    alias
                    for alias in aliases
                    if alias in accepted and accepted[alias] != bindings.get(alias)
                )
        if not blocked:
            return accepted
        for alias in blocked:
            accepted.pop(alias)
