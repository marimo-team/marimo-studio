"""Validate provider starters, the notebook context they read, and their plans."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import cast

from marimo_studio._filesystem.budgets import BUILD_INPUT_BUDGET, FileBudgetTracker
from marimo_studio.view_providers import (
    CellRef,
    CellSpec,
    ProviderStarter,
    StarterCellTarget,
    StarterContext,
    StarterPlan,
)
from marimo_studio.view_providers._host._shapes import (
    MAX_DOCUMENTS,
    checked_json,
    checked_text,
    checked_tuple,
    conformance_error,
    is_manifest,
    provider_path,
    require_disjoint_paths,
    require_unique,
)
from marimo_studio.view_providers._targets import (
    MAX_CELL_TARGETS,
    validate_projection_target,
)

_STARTER_KEY = re.compile(r"[a-z0-9](?:[a-z0-9._/-]*[a-z0-9])?")
_MAX_STARTERS = 256
_MAX_STARTER_CELLS = 4_096
_MAX_STARTER_SOURCE_BYTES = BUILD_INPUT_BUDGET.max_file_bytes
_MAX_STARTER_METADATA_RECORDS = 1_000_000
_MAX_STARTER_CONTEXT_BYTES = 96 * 1024 * 1024


def validate_starters(provider: str, value: object) -> tuple[ProviderStarter, ...]:
    records = checked_tuple(value, provider, "starters", maximum=_MAX_STARTERS)
    starters: list[ProviderStarter] = []
    keys: list[str] = []
    for item in records:
        if not isinstance(item, ProviderStarter):
            raise conformance_error(provider, "requires ProviderStarter records")
        key = checked_text(item.key, provider, "starter key")
        if _STARTER_KEY.fullmatch(key) is None:
            raise conformance_error(provider, f"declares invalid starter key {key!r}")
        checked_text(item.title, provider, "starter title")
        checked_text(item.summary, provider, "starter summary")
        documents = tuple(
            provider_path(path, provider, "starter document")
            for path in checked_tuple(
                item.documents,
                provider,
                "starter documents",
                maximum=MAX_DOCUMENTS,
            )
        )
        if any(is_manifest(path) for path in documents):
            raise conformance_error(
                provider, "reserves top-level 'view.toml' for Studio"
            )
        if not documents:
            raise conformance_error(provider, f"starter {key!r} requires a document")
        require_unique(documents, provider, "starter documents")
        require_disjoint_paths(documents, provider, "starter document")
        keys.append(key)
        starters.append(item)
    require_unique(tuple(keys), provider, "starter keys")
    return tuple(starters)


def validate_starter_context(key: str, value: object) -> StarterContext:
    if not isinstance(value, StarterContext):
        raise conformance_error(key, "requires a StarterContext record")
    checked_text(value.view_name, key, "starter view name")
    checked_text(value.notebook_name, key, "starter notebook name")
    notebook = value.notebook
    if not isinstance(notebook.path, Path) or not isinstance(notebook.revision, str):
        raise conformance_error(key, "requires a saved starter notebook")
    if len(notebook.revision) != 64 or any(
        character not in "0123456789abcdef" for character in notebook.revision
    ):
        raise conformance_error(key, "requires a SHA-256 starter notebook revision")
    cells = checked_tuple(
        notebook.cells,
        key,
        "starter notebook cells",
        maximum=_MAX_STARTER_CELLS,
    )
    refs: list[CellRef] = []
    runtime_ids: list[str] = []
    source_bytes = 0
    metadata_records = 0
    context_bytes = sum(
        len(value.encode("utf-8"))
        for value in (
            value.view_name,
            value.notebook_name,
            str(notebook.path),
            notebook.revision,
        )
    )
    for index, item in enumerate(cells):
        if not isinstance(item, CellSpec) or item.index != index:
            raise conformance_error(key, "requires ordered CellSpec records")
        if item.kind not in {"cell", "setup", "function", "class", "unparsable"}:
            raise conformance_error(
                key,
                "requires recognized starter notebook cell kinds",
            )
        if item.code is None or not isinstance(item.code, str):
            raise conformance_error(key, "requires starter notebook cell code")
        if (
            type(item.has_output_expression) is not bool
            or type(item.may_display_output) is not bool
        ):
            raise conformance_error(
                key,
                "requires has_output_expression and may_display_output to be booleans",
            )
        source_bytes += len(item.code.encode("utf-8"))
        context_bytes += 256 + sum(
            len(text.encode("utf-8"))
            for text in (
                item.runtime_id,
                item.name or "",
                item.preview,
                item.markdown or "",
                item.code,
            )
        )
        context_bytes += sum(
            len(text.encode("utf-8")) for text in item.definitions
        ) + sum(len(text.encode("utf-8")) for text in item.references)
        context_bytes += sum(
            len(str(ref).encode("utf-8")) for ref in item.upstream
        ) + sum(len(str(ref).encode("utf-8")) for ref in item.downstream)
        if source_bytes > _MAX_STARTER_SOURCE_BYTES:
            raise conformance_error(
                key,
                "requires starter notebook source to fit within the file budget",
            )
        digest = hashlib.sha256(item.code.encode("utf-8")).hexdigest()
        if digest != item.code_sha256:
            raise conformance_error(
                key, "requires current starter notebook cell digests"
            )
        if item.name is not None:
            checked_text(item.name, key, "starter notebook cell name")
        if item.markdown is not None and not isinstance(item.markdown, str):
            raise conformance_error(key, "requires text starter notebook markdown")
        refs.append(item.ref)
        runtime_ids.append(item.runtime_id)
        metadata_records += (
            len(item.definitions)
            + len(item.references)
            + len(item.upstream)
            + len(item.downstream)
        )
        if metadata_records > _MAX_STARTER_METADATA_RECORDS:
            raise conformance_error(
                key,
                "limits starter notebook graph and symbol metadata to "
                f"{_MAX_STARTER_METADATA_RECORDS} records",
            )
    require_unique(tuple(refs), key, "starter notebook cell refs")
    require_unique(tuple(runtime_ids), key, "starter notebook runtime cell IDs")
    available_refs = set(refs)
    for item in cast(tuple[CellSpec, ...], cells):
        if not set(item.upstream).issubset(available_refs) or not set(
            item.downstream
        ).issubset(available_refs):
            raise conformance_error(key, "requires contained starter notebook edges")
    app_config = checked_json(
        notebook.app_config,
        key,
        "starter notebook app config",
    )
    if not isinstance(app_config, dict):
        raise conformance_error(key, "requires a starter notebook app config object")
    context_bytes += len(
        json.dumps(
            app_config,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    if not isinstance(value.cell_targets, Mapping):
        raise conformance_error(key, "requires starter cell targets to be a mapping")
    ordinary_refs = {
        item.ref for item in cast(tuple[CellSpec, ...], cells) if item.kind == "cell"
    }
    if set(value.cell_targets) != ordinary_refs:
        raise conformance_error(key, "requires one target for every notebook cell")
    targets: dict[CellRef, StarterCellTarget] = {}
    names: list[str] = []
    for ref, item in value.cell_targets.items():
        if (
            not isinstance(ref, CellRef)
            or not isinstance(item, StarterCellTarget)
            or item.cell != ref
        ):
            raise conformance_error(key, "requires StarterCellTarget records")
        try:
            target = validate_projection_target("cell", item.target)
        except ValueError as error:
            raise conformance_error(
                key,
                f"declares invalid starter cell target: {error}",
            ) from error
        targets[ref] = StarterCellTarget(ref, target)
        names.append(target)
        context_bytes += len(str(ref).encode("utf-8")) + len(target.encode("utf-8"))
    require_unique(tuple(names), key, "starter cell target names")
    if context_bytes > _MAX_STARTER_CONTEXT_BYTES:
        raise conformance_error(
            key,
            "limits encoded starter notebook context to "
            f"{_MAX_STARTER_CONTEXT_BYTES} bytes",
        )
    normalized_notebook = replace(
        notebook,
        cells=cast(tuple[CellSpec, ...], cells),
        app_config=cast(dict[str, object], app_config),
    )
    return StarterContext(
        view_name=value.view_name,
        notebook_name=value.notebook_name,
        notebook=normalized_notebook,
        cell_targets=MappingProxyType(targets),
    )


def validate_starter_plan(
    key: str,
    starter: ProviderStarter,
    context: StarterContext,
    value: object,
) -> StarterPlan:
    validate_starters(key, (starter,))
    if not isinstance(value, StarterPlan):
        raise conformance_error(key, "requires a StarterPlan record")
    files = _validate_starter_files(key, starter, value.files)
    targets = checked_tuple(
        value.cell_targets,
        key,
        "starter plan cell targets",
        maximum=MAX_CELL_TARGETS,
    )
    selected: list[StarterCellTarget] = []
    for item in targets:
        if not isinstance(item, StarterCellTarget):
            raise conformance_error(
                key, "requires StarterCellTarget records in its plan"
            )
        if context.cell_targets.get(item.cell) != item:
            raise conformance_error(
                key,
                f"returned undeclared cell target {item.target!r}",
            )
        selected.append(item)
    require_unique(tuple(selected), key, "starter plan cell targets")
    require_unique(
        tuple(item.target for item in selected),
        key,
        "starter plan cell target names",
    )
    return StarterPlan(files=files, cell_targets=tuple(selected))


def _validate_starter_files(
    key: str,
    starter: ProviderStarter,
    value: object,
) -> Mapping[PurePosixPath, bytes]:
    if not isinstance(value, Mapping) or not value:
        raise conformance_error(key, "requires starter files")
    tracker = FileBudgetTracker(BUILD_INPUT_BUDGET, "Provider starter")
    tracker.require_count(len(value))
    files: dict[PurePosixPath, bytes] = {}
    for raw_path, payload in value.items():
        path = provider_path(raw_path, key, "starter file path")
        if is_manifest(path):
            raise conformance_error(key, "reserves top-level 'view.toml' for Studio")
        if type(payload) is not bytes:
            raise conformance_error(
                key, f"requires {path.as_posix()!r} to contain bytes"
            )
        tracker.add(path.as_posix(), len(cast(bytes, payload)))
        files[path] = cast(bytes, payload)
    require_disjoint_paths(files, key, "starter")
    missing = sorted(set(starter.documents) - files.keys())
    if missing:
        raise conformance_error(
            key,
            f"starter omits document {missing[0].as_posix()!r}",
        )
    return MappingProxyType(files)
