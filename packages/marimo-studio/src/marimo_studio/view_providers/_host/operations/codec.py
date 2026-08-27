"""JSON records exchanged with one isolated provider operation."""

from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Literal, cast

from marimo_studio._filesystem.budgets import PROJECT_INPUT_BUDGET, FileBudgetTracker
from marimo_studio.view_providers import (
    BuildResult,
    JsonValue,
    MountDeclaration,
    ProjectDiagnostic,
    ProjectInput,
    ProjectInspection,
    ProviderAvailability,
    ProviderInfo,
    ProviderStarter,
    SourceDocument,
    SourceLocation,
    StarterContext,
    ViewProject,
)


def project_payload(project: ViewProject) -> dict[str, object]:
    return {
        "name": project.name,
        "root": str(project.root),
        "manifest": str(project.manifest),
        "provider": project.provider,
        "options": dict(project.options),
    }


def provider_info_payload(info: ProviderInfo) -> dict[str, object]:
    return info.to_dict()


def provider_info_from_payload(value: object) -> ProviderInfo:
    data = _record(
        value,
        {"schema", "title", "summary", "api_version"},
        "provider info",
    )
    if data["schema"] != 1 or type(data["api_version"]) is not int:
        raise ValueError("Provider info schema is unsupported")
    return ProviderInfo(
        _text(data["title"], "provider title"),
        _text(data["summary"], "provider summary"),
        data["api_version"],
    )


def availability_payload(value: ProviderAvailability) -> dict[str, object]:
    return value.to_dict()


def availability_from_payload(value: object) -> ProviderAvailability:
    data = _record(
        value,
        {"available", "version", "reason", "action"},
        "provider availability",
    )
    if type(data["available"]) is not bool:
        raise ValueError("Provider availability must contain a boolean state")
    return ProviderAvailability(
        data["available"],
        _optional_text(data["version"], "provider availability version"),
        _optional_text(data["reason"], "provider availability reason"),
        _optional_text(data["action"], "provider availability action"),
    )


def starter_payload(value: ProviderStarter) -> dict[str, object]:
    return value.to_dict()


def starter_from_payload(value: object) -> ProviderStarter:
    data = _record(
        value,
        {"schema", "key", "title", "summary", "documents"},
        "provider starter",
    )
    if data["schema"] != 1:
        raise ValueError("Provider starter schema is unsupported")
    return ProviderStarter(
        _text(data["key"], "provider starter key"),
        _text(data["title"], "provider starter title"),
        _text(data["summary"], "provider starter summary"),
        tuple(
            PurePosixPath(_text(item, "provider starter document"))
            for item in _items(data["documents"])
        ),
    )


def starters_payload(values: tuple[ProviderStarter, ...]) -> list[dict[str, object]]:
    return [starter_payload(value) for value in values]


def starters_from_payload(value: object) -> tuple[ProviderStarter, ...]:
    return tuple(starter_from_payload(item) for item in _items(value))


def starter_context_payload(value: StarterContext) -> dict[str, str]:
    return {"view_name": value.view_name, "notebook_name": value.notebook_name}


def starter_context_from_payload(value: object) -> StarterContext:
    data = _record(value, {"view_name", "notebook_name"}, "starter context")
    return StarterContext(
        _text(data["view_name"], "starter view name"),
        _text(data["notebook_name"], "starter notebook name"),
    )


def created_files_payload(
    files: Mapping[PurePosixPath, bytes],
    transfer_root: Path,
) -> dict[str, object]:
    transfer_root.mkdir(mode=0o700)
    records: list[dict[str, object]] = []
    for index, (path, payload) in enumerate(
        sorted(files.items(), key=lambda item: item[0].as_posix())
    ):
        blob = f"{index:08x}.bin"
        target = transfer_root / blob
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(target, flags, 0o600)
        try:
            view = memoryview(payload)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise OSError("Provider starter transfer stopped before completion")
                view = view[written:]
        finally:
            os.close(descriptor)
        records.append(
            {
                "path": path.as_posix(),
                "blob": blob,
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    return {"files": records}


def created_files_from_payload(
    value: object,
    transfer_root: Path,
) -> Mapping[PurePosixPath, bytes]:
    data = _record(value, {"files"}, "provider starter files")
    items = _items(data["files"])
    tracker = FileBudgetTracker(PROJECT_INPUT_BUDGET, "Provider starter")
    tracker.require_count(len(items))
    files: dict[PurePosixPath, bytes] = {}
    for index, item in enumerate(items):
        record = _record(
            item,
            {"path", "blob", "size", "sha256"},
            "provider starter file",
        )
        path = PurePosixPath(_text(record["path"], "provider starter file path"))
        blob = _text(record["blob"], "provider starter blob")
        if blob != f"{index:08x}.bin":
            raise ValueError("Provider starter blob identity is invalid")
        size = record["size"]
        if type(size) is not int or size < 0:
            raise ValueError("Provider starter blob size is invalid")
        expected_digest = _text(record["sha256"], "provider starter digest")
        if len(expected_digest) != 64:
            raise ValueError("Provider starter digest is invalid")
        tracker.add(path.as_posix(), size)
        payload = _read_blob(transfer_root / blob, size)
        if hashlib.sha256(payload).hexdigest() != expected_digest:
            raise ValueError("Provider starter blob digest does not match")
        if path in files:
            raise ValueError("Provider starter file paths must be unique")
        files[path] = payload
    return files


def inspection_payload(inspection: ProjectInspection) -> dict[str, object]:
    return inspection.to_dict()


def build_result_payload(result: BuildResult) -> dict[str, object]:
    return {
        "document": result.document.as_posix() if result.document is not None else None,
        "diagnostics": [item.to_dict() for item in result.diagnostics],
    }


def project_from_payload(value: object) -> ViewProject:
    data = _record(
        value,
        {"name", "root", "manifest", "provider", "options"},
        "provider project",
    )
    options = data["options"]
    if not isinstance(options, dict) or not all(
        isinstance(key, str) for key in options
    ):
        raise ValueError("Provider project options must be a JSON object")
    return ViewProject(
        _text(data["name"], "provider project name"),
        Path(_text(data["root"], "provider project root")),
        Path(_text(data["manifest"], "provider project manifest")),
        _text(data["provider"], "provider project provider"),
        cast(Mapping[str, JsonValue], options),
    )


def inspection_from_payload(value: object) -> ProjectInspection:
    data = _record(
        value,
        {
            "schema",
            "editor_documents",
            "input_scope",
            "mounts",
            "diagnostics",
            "build_fingerprint",
        },
        "provider inspection",
    )
    if data["schema"] != 1:
        raise ValueError("Provider inspection schema is unsupported")
    return ProjectInspection(
        tuple(_source_document(item) for item in _items(data["editor_documents"])),
        tuple(_project_input(item) for item in _items(data["input_scope"])),
        tuple(_mount(item) for item in _items(data["mounts"])),
        tuple(_diagnostic(item) for item in _items(data["diagnostics"])),
        _text(data["build_fingerprint"], "provider build fingerprint"),
    )


def build_result_from_payload(value: object) -> BuildResult:
    data = _record(value, {"document", "diagnostics"}, "provider build result")
    raw_document = data["document"]
    document = (
        None
        if raw_document is None
        else PurePosixPath(_text(raw_document, "provider build document"))
    )
    return BuildResult(
        document,
        tuple(_diagnostic(item) for item in _items(data["diagnostics"])),
    )


def _source_document(value: object) -> SourceDocument:
    data = _record(value, {"path", "language", "access", "label"}, "source document")
    access = _text(data["access"], "source document access")
    label = data["label"]
    if label is not None:
        label = _text(label, "source document label")
    return SourceDocument(
        PurePosixPath(_text(data["path"], "source document path")),
        _text(data["language"], "source document language"),
        cast(Literal["edit", "read"], access),
        label,
    )


def _project_input(value: object) -> ProjectInput:
    data = _record(value, {"path", "kind"}, "project input")
    return ProjectInput(
        PurePosixPath(_text(data["path"], "project input path")),
        cast(Literal["file", "directory"], _text(data["kind"], "project input kind")),
    )


def _source_location(value: object) -> SourceLocation:
    data = _record(value, {"path", "line", "column"}, "source location")
    line = data["line"]
    column = data["column"]
    if type(line) is not int or type(column) is not int:
        raise ValueError("Source location coordinates must be integers")
    return SourceLocation(
        PurePosixPath(_text(data["path"], "source location path")),
        line,
        column,
    )


def _mount(value: object) -> MountDeclaration:
    data = _record(value, {"id", "kind", "source", "allowedTargets"}, "mount")
    raw_targets = data["allowedTargets"]
    targets = (
        None
        if raw_targets is None
        else tuple(_text(item, "mount target") for item in _items(raw_targets))
    )
    return MountDeclaration(
        _text(data["id"], "mount id"),
        cast(Literal["cell", "output", "value"], _text(data["kind"], "mount kind")),
        _source_location(data["source"]),
        targets,
    )


def _diagnostic(value: object) -> ProjectDiagnostic:
    data = _record(
        value,
        {"code", "severity", "message", "hint", "source"},
        "provider diagnostic",
    )
    return ProjectDiagnostic(
        _text(data["code"], "provider diagnostic code"),
        cast(
            Literal["warning", "error"],
            _text(data["severity"], "provider diagnostic severity"),
        ),
        _text(data["message"], "provider diagnostic message", empty=True),
        _text(data["hint"], "provider diagnostic hint", empty=True),
        None if data["source"] is None else _source_location(data["source"]),
    )


def _record(value: object, fields: set[str], label: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(f"{label.capitalize()} has invalid fields")
    return cast(dict[str, object], value)


def _items(value: object) -> list[object]:
    if not isinstance(value, list):
        raise ValueError("Provider operation collection must be an array")
    return cast(list[object], value)


def _optional_text(value: object, label: str) -> str | None:
    return None if value is None else _text(value, label)


def _text(value: object, label: str, *, empty: bool = False) -> str:
    if not isinstance(value, str) or (not empty and not value):
        raise ValueError(f"{label.capitalize()} must be a string")
    return value


def _read_blob(path: Path, expected_size: int) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        state = os.fstat(descriptor)
        if not stat.S_ISREG(state.st_mode) or state.st_size != expected_size:
            raise ValueError("Provider starter blob size does not match")
        chunks: list[bytes] = []
        remaining = expected_size
        while remaining:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                raise ValueError("Provider starter blob changed while read")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise ValueError("Provider starter blob changed while read")
        return b"".join(chunks)
    finally:
        os.close(descriptor)
