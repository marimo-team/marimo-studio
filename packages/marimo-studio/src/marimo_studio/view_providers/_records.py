"""Stable records and protocols implemented by view providers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal, Protocol

from marimo_studio._filesystem.paths import validate_relative_path
from marimo_studio._notebook.records import CellRef, NotebookSpec
from marimo_studio._processes.operation import (
    ProviderCancellation,
    ProviderRunner,
)

JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
BuildProfile = Literal["development", "production"]
DocumentAccess = Literal["edit", "read"]
ProjectionKind = Literal["cell", "output", "value"]
BuildInputKind = Literal["file", "directory"]


@dataclass(frozen=True)
class ProviderInfo:
    """Describe a provider in the view picker.

    ``options`` names the ``view.toml`` options the provider reads. Studio
    rejects any other option before it inspects or builds a view.
    """

    title: str
    summary: str
    options: frozenset[str] = frozenset()

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": 1,
            "title": self.title,
            "summary": self.summary,
            "options": sorted(self.options),
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

    def path_option(
        self,
        name: str,
        *,
        default: str,
        suffix: str | None = None,
    ) -> PurePosixPath:
        """Return a project-relative path option from ``view.toml``.

        Raises ``ProviderError`` located at ``view.toml`` when the option is not
        a relative POSIX path inside the project, or lacks ``suffix``.
        """
        try:
            path = validate_relative_path(
                self.options.get(name, default),
                field=f"view.toml option {name!r}",
            )
            if suffix is not None and path.suffix.lower() != suffix.lower():
                raise ValueError(f"view.toml option {name!r} must name a {suffix} file")
        except ValueError as error:
            raise ProviderError(
                str(error),
                hint=f"Set {name} in view.toml to a path such as {default!r}.",
                source=SourceLocation(PurePosixPath("view.toml"), 1, 1),
                code="provider-options-invalid",
            ) from error
        return path


@dataclass(frozen=True)
class SourceDocument:
    """One Source document: a UTF-8 text file shown in Studio's Source panel."""

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
class BuildInput:
    """One build input: an exact file or a bounded recursive directory."""

    path: PurePosixPath
    kind: BuildInputKind

    def to_dict(self) -> dict[str, str]:
        return {"path": self.path.as_posix(), "kind": self.kind}


@dataclass(frozen=True)
class SourceLocation:
    path: PurePosixPath
    line: int
    column: int

    def to_dict(self) -> dict[str, object]:
        return {"path": self.path.as_posix(), "line": self.line, "column": self.column}


class ProviderError(Exception):
    """Report a problem with a view project as a diagnostic.

    Raise it from ``inspect()`` or ``build()``. Studio shows
    ``message`` and ``hint`` beside ``source`` instead of a provider failure.
    """

    def __init__(
        self,
        message: str,
        *,
        hint: str = "",
        source: SourceLocation | None = None,
        code: str = "provider-error",
    ) -> None:
        super().__init__(message)
        self.diagnostic = ProjectDiagnostic(
            code, "error", message.strip(), hint.strip(), source
        )


@dataclass(frozen=True)
class ProjectionSite:
    """One projection site: the source location of a projection host.

    ``offset`` is the UTF-8 byte offset inside the host's start tag where Studio
    inserts the runtime site attribute in the build snapshot. An output site
    with ``accept`` shows the value in the first of those media types it
    supports, such as ``("image/svg+xml",)`` for a crisp figure. Without
    ``accept``, the site shows marimo's native output.
    """

    kind: ProjectionKind
    targets: tuple[str, ...] | Literal["*"]
    source: SourceLocation
    offset: int
    accept: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "targets": self.targets if self.targets == "*" else list(self.targets),
            "source": self.source.to_dict(),
            "offset": self.offset,
            "accept": list(self.accept),
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
    """Describe a view project's Source documents, build inputs, and sites.

    Studio adds ``view.toml`` to the inputs, and shows ``AGENTS.md`` and
    ``DESIGN.md`` in Source when they exist.
    """

    documents: tuple[SourceDocument, ...]
    inputs: tuple[BuildInput, ...]
    sites: tuple[ProjectionSite, ...] = ()
    diagnostics: tuple[ProjectDiagnostic, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": 2,
            "documents": [item.to_dict() for item in self.documents],
            "inputs": [item.to_dict() for item in self.inputs],
            "sites": [item.to_dict() for item in self.sites],
            "diagnostics": [item.to_dict() for item in self.diagnostics],
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

    @property
    def app_title(self) -> str | None:
        """Return the notebook's configured app title, if it has one."""
        configured = self.notebook.app_config.get("app_title")
        if isinstance(configured, str) and configured.strip():
            return configured.strip()
        return None

    @property
    def notebook_label(self) -> str:
        """Return the notebook's app title, or a readable form of its filename."""
        return (
            self.app_title
            or " ".join(
                self.notebook_name.replace("_", " ").replace("-", " ").split()
            ).title()
        )

    @property
    def output_cells(self) -> tuple[StarterCellTarget, ...]:
        """Return targets for runnable cells that may display output.

        Cells that are disabled, or downstream of a disabled cell, never run.
        """
        cells = self.notebook.by_ref()
        disabled = {cell.ref for cell in self.notebook.cells if cell.config.disabled}
        pending = list(disabled)
        while pending:
            for child in cells[pending.pop()].downstream:
                if child not in disabled:
                    disabled.add(child)
                    pending.append(child)
        return tuple(
            self.cell_targets[cell.ref]
            for cell in self.notebook.cells
            if cell.kind == "cell"
            and cell.ref not in disabled
            and cell.may_display_output
        )


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
    work_root: Path
    cache_root: Path
    cancellation: ProviderCancellation
    runner: ProviderRunner
    command_timeout: float


@dataclass(frozen=True)
class BuildResult:
    document: PurePosixPath | None
    diagnostics: tuple[ProjectDiagnostic, ...] = ()


class ViewProvider(Protocol):
    """Create, inspect, and build one kind of view project."""

    info: ProviderInfo

    def availability(self) -> ProviderAvailability: ...

    def starters(self) -> tuple[ProviderStarter, ...]: ...

    def create(
        self,
        starter: ProviderStarter,
        context: StarterContext,
    ) -> StarterPlan: ...

    def inspect(self, request: InspectionRequest) -> ProjectInspection: ...

    def build(self, request: BuildRequest) -> BuildResult: ...
