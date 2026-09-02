"""Stable records and protocols implemented by view providers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal, Protocol

from marimo_studio._notebook.records import CellRef, NotebookSpec
from marimo_studio.view_providers._operation import (
    ProviderCancellation,
    ProviderRunner,
)

JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
BuildProfile = Literal["development", "production"]
DocumentAccess = Literal["edit", "read"]
ProjectionKind = Literal["cell", "output", "value"]
ProjectInputKind = Literal["file", "directory"]
PROVIDER_API_VERSION = 1


@dataclass(frozen=True)
class ProviderInfo:
    """Describe the provider contract shown in discovery and diagnostics."""

    title: str
    summary: str
    api_version: int

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": 1,
            "title": self.title,
            "summary": self.summary,
            "api_version": self.api_version,
        }


@dataclass(frozen=True)
class ProviderAvailability:
    available: bool
    version: str | None = None
    reason: str | None = None
    action: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "available": self.available,
            "version": self.version,
            "reason": self.reason,
            "action": self.action,
        }


@dataclass(frozen=True)
class ProviderStarter:
    key: str
    title: str
    summary: str
    documents: tuple[PurePosixPath, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": 1,
            "key": self.key,
            "title": self.title,
            "summary": self.summary,
            "documents": [item.as_posix() for item in self.documents],
        }


@dataclass(frozen=True)
class ViewProject:
    name: str
    root: Path
    manifest: Path
    provider: str
    options: Mapping[str, JsonValue]


@dataclass(frozen=True)
class SourceDocument:
    """Describe one text document exposed through provider inspection."""

    path: PurePosixPath
    language: str
    access: DocumentAccess
    label: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path.as_posix(),
            "language": self.language,
            "access": self.access,
            "label": self.label,
        }


@dataclass(frozen=True)
class ProjectInput:
    """Declare one exact file or bounded recursive project directory."""

    path: PurePosixPath
    kind: ProjectInputKind

    def to_dict(self) -> dict[str, str]:
        return {"path": self.path.as_posix(), "kind": self.kind}


@dataclass(frozen=True)
class SourceLocation:
    path: PurePosixPath
    line: int
    column: int

    def to_dict(self) -> dict[str, object]:
        return {"path": self.path.as_posix(), "line": self.line, "column": self.column}


@dataclass(frozen=True)
class MountDeclaration:
    id: str
    kind: ProjectionKind
    source: SourceLocation
    allowed_targets: tuple[str, ...] | None

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "kind": self.kind,
            "source": self.source.to_dict(),
            "allowedTargets": (
                list(self.allowed_targets) if self.allowed_targets is not None else None
            ),
        }


@dataclass(frozen=True)
class ProjectDiagnostic:
    code: str
    severity: Literal["warning", "error"]
    message: str
    hint: str = ""
    source: SourceLocation | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "hint": self.hint,
            "source": self.source.to_dict() if self.source is not None else None,
        }


@dataclass(frozen=True)
class ProjectInspection:
    editor_documents: tuple[SourceDocument, ...]
    input_scope: tuple[ProjectInput, ...]
    mounts: tuple[MountDeclaration, ...]
    diagnostics: tuple[ProjectDiagnostic, ...]
    build_fingerprint: str

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": 1,
            "editor_documents": [item.to_dict() for item in self.editor_documents],
            "input_scope": [item.to_dict() for item in self.input_scope],
            "mounts": [item.to_dict() for item in self.mounts],
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "build_fingerprint": self.build_fingerprint,
        }


@dataclass(frozen=True)
class StarterCellTarget:
    """Name one saved notebook cell in generated provider source."""

    cell: CellRef
    target: str

    def to_dict(self) -> dict[str, str]:
        return {"cell": str(self.cell), "target": self.target}


@dataclass(frozen=True)
class StarterContext:
    """Describe the saved notebook revision used to create a view project."""

    view_name: str
    notebook_name: str
    notebook: NotebookSpec
    cell_targets: Mapping[CellRef, StarterCellTarget]


@dataclass(frozen=True)
class StarterPlan:
    """Return generated project files and the cell targets they contain."""

    files: Mapping[PurePosixPath, bytes]
    cell_targets: tuple[StarterCellTarget, ...]


@dataclass(frozen=True)
class InspectionRequest:
    project: ViewProject
    runner: ProviderRunner
    cancellation: ProviderCancellation
    cache_root: Path
    command_timeout: float


@dataclass(frozen=True)
class BuildRequest:
    project: ViewProject
    inspection: ProjectInspection
    inputs: tuple[PurePosixPath, ...]
    project_revision: str
    profile: BuildProfile
    staging_root: Path
    cache_root: Path
    cancellation: ProviderCancellation
    runner: ProviderRunner
    command_timeout: float


@dataclass(frozen=True)
class BuildResult:
    document: PurePosixPath | None
    diagnostics: tuple[ProjectDiagnostic, ...]


class ViewProvider(Protocol):
    info: ProviderInfo

    def availability(
        self,
        project: ViewProject | None = None,
    ) -> ProviderAvailability: ...

    def starters(self) -> tuple[ProviderStarter, ...]: ...

    def create(
        self,
        starter: ProviderStarter,
        context: StarterContext,
    ) -> StarterPlan: ...

    def inspect(self, request: InspectionRequest) -> ProjectInspection: ...

    def build(self, request: BuildRequest) -> BuildResult: ...
