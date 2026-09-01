"""Publish browser-native HTML views with direct leaf CSS and JavaScript."""

from __future__ import annotations

import shutil
from pathlib import PurePosixPath

from marimo_studio._filesystem.io import reject_mutable_symlinks
from marimo_studio.errors import ConfigurationError, ViewProjectError
from marimo_studio.view_providers import (
    PROVIDER_API_VERSION,
    BuildRequest,
    BuildResult,
    InspectionRequest,
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
from marimo_studio.view_providers._bundled._starters import (
    create_starter,
    provider_starters,
)
from marimo_studio.view_providers._bundled.vanilla._sources import (
    VanillaLocalDependencyError,
    VanillaSourceGraph,
    VanillaSourceGraphError,
    vanilla_entry_document,
    vanilla_entry_path,
)
from marimo_studio.view_providers._bundled.vanilla.starters import (
    catalog as _STARTERS,
)
from marimo_studio.view_providers._document import HTMLLocalResourceError

_AGENT_INSTRUCTIONS_PATH = PurePosixPath("AGENTS.md")
_OPTIONAL_DESIGN_PATH = PurePosixPath("DESIGN.md")
_BUILD_FINGERPRINT = "vanilla-html-v4"


def _guidance_documents(project: ViewProject) -> tuple[SourceDocument, ...]:
    documents: list[SourceDocument] = []
    for relative in (_AGENT_INSTRUCTIONS_PATH, _OPTIONAL_DESIGN_PATH):
        path = project.root / relative
        if not path.exists():
            continue
        reject_mutable_symlinks(project.root, {path})
        if not path.is_file():
            raise ConfigurationError(f"Vanilla guidance is unavailable: {relative}")
        documents.append(SourceDocument(relative, "markdown", "edit"))
    return tuple(documents)


def _entry_failure(
    entry: PurePosixPath,
    error: Exception,
) -> ProjectInspection:
    return ProjectInspection(
        editor_documents=(),
        input_scope=VanillaSourceGraph.inputs_for(entry),
        mounts=(),
        diagnostics=(
            ProjectDiagnostic(
                code="entry-document-invalid",
                severity="error",
                message=str(error),
                hint="Restore the HTML entry document and build the view again.",
            ),
        ),
        build_fingerprint=f"{_BUILD_FINGERPRINT}:{entry.as_posix()}",
    )


def _source_diagnostic(
    entry: PurePosixPath,
    error: Exception,
) -> ProjectDiagnostic:
    if isinstance(error, HTMLLocalResourceError):
        return ProjectDiagnostic(
            code="local-resource-invalid",
            severity="error",
            message=str(error),
            hint=(
                "Reference local CSS with <link rel=stylesheet href> and local "
                "JavaScript with <script src>. Keep other local assets inline "
                "in the HTML entry document."
            ),
            source=SourceLocation(entry, error.line or 1, error.column or 1),
        )
    if isinstance(error, VanillaLocalDependencyError):
        return ProjectDiagnostic(
            code="local-source-dependency",
            severity="error",
            message=str(error),
            hint=error.public_hint,
            source=SourceLocation(
                PurePosixPath(str(error.source)),
                error.line or 1,
                error.column or 1,
            ),
        )
    line = error.line if isinstance(error, ViewProjectError) else None
    column = error.column if isinstance(error, ViewProjectError) else None
    hint = (
        error.public_hint
        if isinstance(error, ViewProjectError)
        else "Restore the HTML entry document and build the view again."
    )
    return ProjectDiagnostic(
        code="entry-document-invalid",
        severity="error",
        message=str(error),
        hint=hint,
        source=SourceLocation(entry, line or 1, column or 1),
    )


def _cancelled_build() -> BuildResult:
    return BuildResult(
        None,
        (
            ProjectDiagnostic(
                code="build-cancelled",
                severity="error",
                message="The Vanilla build was cancelled.",
            ),
        ),
    )


class VanillaProvider:
    """Inspect and build browser-native view projects."""

    info = ProviderInfo(
        title="Vanilla web",
        summary="Publishes HTML with optional local CSS and JavaScript.",
        api_version=PROVIDER_API_VERSION,
    )

    def availability(self, project: ViewProject | None = None) -> ProviderAvailability:
        del project
        return ProviderAvailability(True)

    def starters(self) -> tuple[ProviderStarter, ...]:
        return provider_starters(_STARTERS)

    def create(
        self,
        starter: ProviderStarter,
        context: StarterContext,
    ) -> StarterPlan:
        return create_starter(_STARTERS, starter, context)

    def inspect(self, request: InspectionRequest) -> ProjectInspection:
        project = request.project
        try:
            entry_path = vanilla_entry_path(project)
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
                build_fingerprint=_BUILD_FINGERPRINT,
            )
        try:
            entry = vanilla_entry_document(project, entry_path)
            guidance = _guidance_documents(project)
        except ConfigurationError as error:
            return _entry_failure(entry_path, error)
        try:
            graph = VanillaSourceGraph.analyze(project, entry)
        except VanillaSourceGraphError as error:
            return ProjectInspection(
                editor_documents=(
                    entry,
                    *error.direct_documents,
                    *guidance,
                ),
                input_scope=error.inputs,
                mounts=error.mounts,
                diagnostics=(_source_diagnostic(entry_path, error.cause),),
                build_fingerprint=(f"{_BUILD_FINGERPRINT}:{entry_path.as_posix()}"),
            )
        return ProjectInspection(
            editor_documents=(*graph.editor_documents, *guidance),
            input_scope=graph.inputs,
            mounts=graph.mounts,
            diagnostics=(),
            build_fingerprint=f"{_BUILD_FINGERPRINT}:{entry_path.as_posix()}",
        )

    def build(self, request: BuildRequest) -> BuildResult:
        source_entry = vanilla_entry_path(request.project)
        if request.cancellation.cancelled:
            return _cancelled_build()
        entry = vanilla_entry_document(request.project, source_entry)
        try:
            graph = VanillaSourceGraph.analyze(
                request.project,
                entry,
                available_inputs=request.inputs,
            )
        except VanillaSourceGraphError as error:
            raise error.cause from error
        instrumented = graph.instrument(request.inspection.mounts)
        for relative in graph.source_paths:
            if request.cancellation.cancelled:
                return _cancelled_build()
            source = request.project.root.joinpath(*relative.parts)
            destination = request.staging_root.joinpath(*relative.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        if request.cancellation.cancelled:
            return _cancelled_build()
        document = request.staging_root.joinpath(*source_entry.parts)
        document.write_text(instrumented, encoding="utf-8")
        return BuildResult(source_entry, ())


provider = VanillaProvider()
