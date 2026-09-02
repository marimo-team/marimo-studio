"""Pure validation for provider-owned records."""

from __future__ import annotations

import re
from collections.abc import Collection
from pathlib import PurePosixPath, PureWindowsPath

from marimo_studio._filesystem.paths import validate_portable_path_component
from marimo_studio.view_providers._records import (
    MountDeclaration,
    ProjectDiagnostic,
    SourceLocation,
)
from marimo_studio.view_providers._targets import (
    MAX_CELL_TARGETS,
    MAX_VALUE_TARGETS,
    validate_projection_target,
)

_MAX_PROVIDER_TEXT_BYTES = 64 * 1024
_MAX_SAFE_INTEGER = (1 << 53) - 1

_PROJECTION_SITE_ID = re.compile(r"[a-z0-9][a-z0-9._:-]{0,127}")
_PROVIDER_KEY = re.compile(
    r"[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?/[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?"
)


def validate_projection_site_id(value: object, *, field: str) -> str:
    if (
        not isinstance(value, str)
        or _PROJECTION_SITE_ID.fullmatch(value) is None
        or value != value.strip()
    ):
        raise ValueError(f"{field} must be a lowercase artifact-local identifier")
    return value


def validate_provider_key(value: object, *, field: str) -> str:
    if (
        not isinstance(value, str)
        or _PROVIDER_KEY.fullmatch(value) is None
        or value != value.strip()
    ):
        raise ValueError(f"{field} must use distribution/entry-point form")
    return value


def validate_relative_path(
    value: object,
    *,
    field: str,
) -> PurePosixPath:
    if not isinstance(value, (str, PurePosixPath)):
        raise ValueError(f"{field} must be a project-relative POSIX path")
    raw = str(value)
    if not raw or raw.startswith("/") or "\\" in raw:
        raise ValueError(f"{field} must be a normalized project-relative POSIX path")
    if PureWindowsPath(raw).drive:
        raise ValueError(f"{field} must not use a Windows drive prefix")
    parts = raw.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"{field} must be a normalized project-relative POSIX path")
    for part in parts:
        validate_portable_path_component(part, field=f"{field} path segment")
    path = PurePosixPath(raw)
    if path.is_absolute() or path.as_posix() != raw:
        raise ValueError(f"{field} must be a normalized project-relative POSIX path")
    return path


def _validate_source_location(
    source: object,
    documents: Collection[PurePosixPath] | None,
    *,
    label: str,
) -> SourceLocation:
    if not isinstance(source, SourceLocation):
        raise ValueError(f"{label} must be a SourceLocation")
    if type(source.path) is not PurePosixPath:
        raise ValueError(f"{label} path must be a PurePosixPath")
    path = validate_relative_path(source.path, field=f"{label} path")
    if len(path.as_posix().encode("utf-8")) > _MAX_PROVIDER_TEXT_BYTES:
        raise ValueError(
            f"{label} path exceeds the {_MAX_PROVIDER_TEXT_BYTES}-byte limit"
        )
    if documents is not None:
        catalog = {
            validate_relative_path(item, field=f"{label} document path")
            for item in documents
        }
        if path not in catalog:
            raise ValueError(
                f"{label} path {path.as_posix()!r} is absent from documents"
            )
    if (
        type(source.line) is not int
        or type(source.column) is not int
        or source.line <= 0
        or source.column <= 0
        or source.line > _MAX_SAFE_INTEGER
        or source.column > _MAX_SAFE_INTEGER
    ):
        raise ValueError(f"{label} coordinates must be positive browser-safe integers")
    return source


def _validate_allowed_targets(
    kind: str,
    value: object,
) -> tuple[str, ...] | None:
    if value is None:
        return None
    if not isinstance(value, tuple) or not value:
        raise ValueError("Mount allowed targets must be a non-empty tuple or None")
    maximum = MAX_CELL_TARGETS if kind == "cell" else MAX_VALUE_TARGETS
    if len(value) > maximum:
        raise ValueError(f"Mount allowed targets exceed the {maximum}-target limit")
    targets = tuple(validate_projection_target(kind, target) for target in value)
    if len(set(targets)) != len(targets):
        raise ValueError("Mount targets must be unique")
    return targets


def validate_mount_declaration(
    value: object,
    *,
    documents: Collection[PurePosixPath] | None = None,
) -> MountDeclaration:
    if not isinstance(value, MountDeclaration):
        raise ValueError("Projection site must be a MountDeclaration record")
    validate_projection_site_id(value.id, field="Projection site ID")
    if value.kind not in {"cell", "output", "value"}:
        raise ValueError("Projection site kind is invalid")
    _validate_source_location(value.source, documents, label="Projection source")
    _validate_allowed_targets(value.kind, value.allowed_targets)
    return value


def validate_project_diagnostic(
    value: object,
    *,
    documents: Collection[PurePosixPath] | None = None,
) -> ProjectDiagnostic:
    if not isinstance(value, ProjectDiagnostic):
        raise ValueError("Project diagnostic must be a ProjectDiagnostic record")
    if (
        not isinstance(value.code, str)
        or re.fullmatch(
            r"[a-z0-9]+(?:-[a-z0-9]+)*",
            value.code,
        )
        is None
    ):
        raise ValueError("Project diagnostic code must be canonical kebab-case")
    if value.severity not in {"warning", "error"}:
        raise ValueError("Project diagnostic severity must be warning or error")
    if not value.message or value.message != value.message.strip():
        raise ValueError("Project diagnostic message must be canonical")
    if value.hint != value.hint.strip():
        raise ValueError("Project diagnostic hint must be canonical")
    if len(value.message.encode("utf-8")) > _MAX_PROVIDER_TEXT_BYTES:
        raise ValueError("Project diagnostic message exceeds the text limit")
    if len(value.hint.encode("utf-8")) > _MAX_PROVIDER_TEXT_BYTES:
        raise ValueError("Project diagnostic hint exceeds the text limit")
    if value.source is not None:
        _validate_source_location(value.source, documents, label="Diagnostic source")
    return value
