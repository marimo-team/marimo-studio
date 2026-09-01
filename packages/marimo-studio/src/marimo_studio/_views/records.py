"""Application records for view creation, inspection, and builds."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from marimo_studio._artifacts.records import (
    ArtifactPublication,
    ViewArtifact,
    ViewBuildState,
)
from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio.view_providers import (
    BuildProfile,
    DocumentAccess,
    ProjectDiagnostic,
    ProviderAvailability,
    SourceDocument,
)

OverviewState = Literal["unconfigured", "needs-view", "ready"]


@dataclass(frozen=True)
class ViewDocument:
    """One revision-bound authored document."""

    path: PurePosixPath
    language: str
    access: DocumentAccess
    content: str
    revision: str

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path.as_posix(),
            "language": self.language,
            "access": self.access,
            "content": self.content,
            "revision": self.revision,
        }


@dataclass(frozen=True)
class ViewSetupResult:
    """Describe one created or repaired view project."""

    workspace: StudioWorkspace | None
    notebook: Path
    config_path: Path
    name: str
    root: Path
    provider: str
    documents: tuple[Path, ...]
    created: tuple[Path, ...]
    updated: tuple[Path, ...]
    dry_run: bool
    launch_requirements: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": 1,
            "notebook": str(self.notebook),
            "config": str(self.config_path),
            "view": self.name,
            "root": str(self.root),
            "provider": self.provider,
            "documents": [str(path) for path in self.documents],
            "created": [str(path) for path in self.created],
            "updated": [str(path) for path in self.updated],
            "dry_run": self.dry_run,
            "launch_requirements": list(self.launch_requirements),
        }


@dataclass(frozen=True)
class ViewOverview:
    """Identify one authored view in a Studio workspace."""

    name: str
    generation: str
    path: Path
    default: bool
    provider: str
    documents: tuple[str, ...]
    artifact_revision: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "generation": self.generation,
            "path": str(self.path),
            "default": self.default,
            "provider": self.provider,
            "documents": list(self.documents),
            "artifact_revision": self.artifact_revision,
        }


@dataclass(frozen=True)
class StudioOverview:
    """Describe configuration and views for one saved notebook."""

    notebook: Path
    state: OverviewState
    generation: str | None
    config_path: Path | None
    config_source: Literal["notebook", "pyproject"] | None
    view_root: Path
    default_view: str | None
    default_runtime: str | None
    runtimes: tuple[str, ...]
    bindings: dict[str, str]
    views: tuple[ViewOverview, ...]
    launch_requirements: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": 1,
            "notebook": str(self.notebook),
            "state": self.state,
            "generation": self.generation,
            "config": str(self.config_path) if self.config_path is not None else None,
            "config_source": self.config_source,
            "view_root": str(self.view_root),
            "default_view": self.default_view,
            "default_runtime": self.default_runtime,
            "runtimes": list(self.runtimes),
            "bindings": self.bindings,
            "views": [view.to_dict() for view in self.views],
            "launch_requirements": list(self.launch_requirements),
        }


@dataclass(frozen=True)
class Starter:
    """Describe one installed starting point for a new view."""

    id: str
    title: str
    summary: str
    provider: str
    documents: tuple[PurePosixPath, ...]
    availability: ProviderAvailability

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": 1,
            "id": self.id,
            "title": self.title,
            "summary": self.summary,
            "provider": self.provider,
            "documents": [item.as_posix() for item in self.documents],
            "availability": self.availability.to_dict(),
        }


@dataclass(frozen=True)
class ViewBuild:
    """Describe the browser page produced by one completed build."""

    view: str
    profile: BuildProfile
    revision: str
    issues: tuple[ProjectDiagnostic, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": 1,
            "view": self.view,
            "profile": self.profile,
            "revision": self.revision,
            "issues": [item.to_dict() for item in self.issues],
        }


@dataclass(frozen=True)
class ViewProjectState:
    """Join the current project revision with build and artifact state."""

    project_revision: str | None
    build: ViewBuildState
    artifact: ViewArtifact | None
    publication: ArtifactPublication | None


@dataclass(frozen=True)
class StudioDiagnostic:
    """Describe one actionable issue in an application-facing view result."""

    code: str
    severity: Literal["warning", "error"]
    message: str
    hint: str
    path: str | None = None
    line: int | None = None
    column: int | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "hint": self.hint,
            "source": (
                {
                    "path": self.path,
                    "line": self.line,
                    "column": self.column,
                }
                if self.path is not None
                else None
            ),
        }


ViewFreshness = Literal["current", "stale", "unbuilt", "building", "failed"]


@dataclass(frozen=True)
class ViewInspection:
    """Return source documents and current build state for one view."""

    view: str
    provider: str
    documents: tuple[SourceDocument, ...]
    diagnostics: tuple[StudioDiagnostic, ...]
    freshness: ViewFreshness
    build: ViewBuild | None

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": 1,
            "view": self.view,
            "provider": self.provider,
            "documents": [item.to_dict() for item in self.documents],
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "freshness": self.freshness,
            "build": self.build.to_dict() if self.build is not None else None,
        }
