"""Records for build attempts and immutable browser publications."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from marimo_studio.view_providers import (
    BuildProfile,
    MountDeclaration,
    ProjectDiagnostic,
)
from marimo_studio.view_providers._host.records import ProviderProvenance

ViewBuildPhase = Literal["unbuilt", "building", "failed", "published", "stale"]
ArtifactTreeIdentity = tuple[tuple[object, ...], ...]


@dataclass(frozen=True)
class ViewBuildState:
    """Describe the latest build attempt and retained published artifact."""

    profile: BuildProfile
    phase: ViewBuildPhase
    project_revision: str | None
    artifact_revision: str | None
    diagnostics: tuple[ProjectDiagnostic, ...]
    duration_ms: int | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": 1,
            "profile": self.profile,
            "phase": self.phase,
            "project_revision": self.project_revision,
            "artifact_revision": self.artifact_revision,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "duration_ms": self.duration_ms,
        }


@dataclass(frozen=True)
class ArtifactFile:
    """Describe one validated public browser file."""

    path: PurePosixPath
    sha256: str
    size: int


@dataclass(frozen=True)
class ViewArtifact:
    """One immutable browser artifact published beneath a view project."""

    root: Path
    profile: BuildProfile
    document: PurePosixPath
    files: tuple[ArtifactFile, ...]
    mounts: tuple[MountDeclaration, ...]
    project_revision: str
    artifact_revision: str
    provider: ProviderProvenance

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": 1,
            "root": str(self.root),
            "profile": self.profile,
            "document": self.document.as_posix(),
            "files": [
                {"path": item.path.as_posix(), "sha256": item.sha256, "size": item.size}
                for item in self.files
            ],
            "mounts": [item.to_dict() for item in self.mounts],
            "project_revision": self.project_revision,
            "artifact_revision": self.artifact_revision,
            "provider": self.provider.to_dict(),
        }


@dataclass(frozen=True)
class ArtifactManifest:
    """Content identity stored once for every immutable artifact revision."""

    artifact_revision: str
    document: PurePosixPath
    files: tuple[ArtifactFile, ...]
    mounts: tuple[MountDeclaration, ...]


@dataclass(frozen=True)
class ArtifactRevision:
    """One verified immutable file tree beneath a view project."""

    root: Path
    manifest: ArtifactManifest

    def file(self, path: PurePosixPath) -> ArtifactFile | None:
        return next((item for item in self.manifest.files if item.path == path), None)


@dataclass(frozen=True)
class ArtifactRevisionSnapshot:
    """One content-verified revision and its cheap filesystem identity."""

    revision: ArtifactRevision
    identity: ArtifactTreeIdentity


@dataclass(frozen=True)
class ArtifactPublication:
    """Profile-specific provenance for one published content revision."""

    project_revision: str
    artifact_revision: str
    provider: ProviderProvenance
    diagnostics: tuple[ProjectDiagnostic, ...]
    duration_ms: int


@dataclass(frozen=True)
class ArtifactProfileState:
    """One profile's current publication and latest build receipt."""

    profile: BuildProfile
    published: ArtifactPublication | None
    build: ViewBuildState


@dataclass(frozen=True)
class ArtifactStateSnapshot:
    """One atomically read profile receipt and verified published artifact."""

    state: ArtifactProfileState | None
    artifact: ViewArtifact | None
    build: ViewBuildState
