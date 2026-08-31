"""Build the multi-document web project used by Studio E2E."""

from __future__ import annotations

import shutil
from pathlib import PurePosixPath

from marimo_studio.view_providers import (
    BuildRequest,
    BuildResult,
    InspectionRequest,
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
    StarterPlan,
    ViewProject,
)

from fixture_provider._html import (
    instrument_literal_mounts,
    mount_declarations,
    parse_literal_mounts,
)

_PROVIDER = "marimo-studio-e2e-provider/web"
_ENTRY = PurePosixPath("src/index.html")
_DOCUMENTS = (
    _ENTRY,
    PurePosixPath("src/app.css"),
    PurePosixPath("src/scripts/app.js"),
    PurePosixPath("src/scripts/message.js"),
)


def _entry_path(project: ViewProject) -> PurePosixPath:
    unknown = sorted(set(project.options) - {"entrypoint"})
    if unknown:
        raise ValueError(f"Web provider received undeclared option {unknown[0]!r}")
    configured = project.options.get("entrypoint", _ENTRY.as_posix())
    if configured != _ENTRY.as_posix():
        raise ValueError(f"Web provider entrypoint must be {_ENTRY}")
    return _ENTRY


class MultiFileProvider:
    info = ProviderInfo(
        title="E2E web project",
        summary="Builds one HTML entry and its declared browser assets.",
        api_version=1,
    )
    _starter = ProviderStarter(
        key="default",
        title="E2E web project",
        summary="HTML, CSS, and JavaScript source documents.",
        documents=_DOCUMENTS,
    )

    def availability(self, project: ViewProject | None = None) -> ProviderAvailability:
        del project
        return ProviderAvailability(True, version="1.0.0")

    def starters(self) -> tuple[ProviderStarter, ...]:
        return (self._starter,)

    def create(
        self,
        starter: ProviderStarter,
        context: StarterContext,
    ) -> StarterPlan:
        if starter != self._starter:
            raise ValueError(f"Unknown starter {starter.key!r}")
        del context
        return StarterPlan(
            files={
                _ENTRY: (
                    b'<!doctype html><html><head><link rel="stylesheet" href="app.css">'
                    b'</head><body><main id="app-shell"></main>'
                    b'<script type="module" src="scripts/app.js"></script></body></html>'
                ),
                PurePosixPath("src/app.css"): b"body { margin: 0; }\n",
                PurePosixPath("src/scripts/app.js"): b'import "./message.js";\n',
                PurePosixPath(
                    "src/scripts/message.js"
                ): b"export const ready = true;\n",
            },
            cell_targets=(),
        )

    def inspect(self, request: InspectionRequest) -> ProjectInspection:
        project = request.project
        try:
            entry = _entry_path(project)
        except ValueError as error:
            return ProjectInspection(
                editor_documents=(),
                input_scope=(ProjectInput(PurePosixPath("view.toml"), "file"),),
                mounts=(),
                diagnostics=(
                    ProjectDiagnostic(
                        code="provider-options-invalid",
                        severity="error",
                        message=str(error),
                    ),
                ),
                build_fingerprint="e2e-web-v1",
            )
        documents = tuple(
            path for path in _DOCUMENTS if project.root.joinpath(*path.parts).is_file()
        )
        diagnostics: tuple[ProjectDiagnostic, ...] = ()
        mounts: tuple[MountDeclaration, ...] = ()
        if entry not in documents:
            diagnostics = (
                ProjectDiagnostic(
                    code="project-document-missing",
                    severity="error",
                    message=f"Web project entry is unavailable: {entry}",
                ),
            )
        else:
            try:
                source = project.root.joinpath(*entry.parts).read_text(encoding="utf-8")
                mounts = mount_declarations(
                    _PROVIDER, entry, parse_literal_mounts(source)
                )
            except (OSError, UnicodeError, ValueError) as error:
                diagnostics = (
                    ProjectDiagnostic(
                        code="entry-document-invalid",
                        severity="error",
                        message=str(error),
                        source=SourceLocation(entry, 1, 1),
                    ),
                )
        return ProjectInspection(
            editor_documents=tuple(
                SourceDocument(
                    path,
                    "html"
                    if path.suffix == ".html"
                    else "css"
                    if path.suffix == ".css"
                    else "javascript",
                    "edit",
                )
                for path in documents
            ),
            input_scope=(
                ProjectInput(PurePosixPath("view.toml"), "file"),
                *(ProjectInput(path, "file") for path in documents),
            ),
            mounts=mounts,
            diagnostics=diagnostics,
            build_fingerprint="e2e-web-v1",
        )

    def build(self, request: BuildRequest) -> BuildResult:
        if request.cancellation.cancelled:
            return BuildResult(
                None,
                (
                    ProjectDiagnostic(
                        code="build-cancelled",
                        severity="error",
                        message="The external web build was cancelled.",
                    ),
                ),
            )
        for document in request.inspection.editor_documents:
            relative = document.path
            source = request.project.root.joinpath(*relative.parts)
            destination = request.staging_root.joinpath(*relative.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if relative == _ENTRY:
                text = source.read_text(encoding="utf-8")
                parsed = parse_literal_mounts(text)
                current = mount_declarations(_PROVIDER, _ENTRY, parsed)
                if current != request.inspection.mounts:
                    raise ValueError("Fixture projection sites changed before build")
                destination.write_text(
                    instrument_literal_mounts(text, parsed, current),
                    encoding="utf-8",
                )
            else:
                shutil.copy2(source, destination)
        return BuildResult(_ENTRY, ())


multi_provider = MultiFileProvider()
