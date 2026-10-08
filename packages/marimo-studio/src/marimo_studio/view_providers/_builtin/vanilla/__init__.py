"""Publish browser-native HTML views with direct leaf CSS and JavaScript."""

from __future__ import annotations

import shutil
from pathlib import PurePosixPath

from marimo_studio._filesystem.files import FileTree
from marimo_studio.errors import ConfigurationError, ViewProjectError
from marimo_studio.view_providers import (
    BuildRequest,
    BuildResult,
    InspectionRequest,
    ProjectDiagnostic,
    ProjectInspection,
    ProviderAvailability,
    ProviderInfo,
    ProviderStarter,
    SourceLocation,
    StarterContext,
    StarterPlan,
    create_starter,
    html_sites,
)
from marimo_studio.view_providers._builtin.vanilla._sources import (
    VanillaLocalDependencyError,
    VanillaSourceGraph,
    VanillaSourceGraphError,
    vanilla_entry_document,
    vanilla_entry_path,
)
from marimo_studio.view_providers._builtin.vanilla.starters import STARTERS
from marimo_studio.view_providers._document import HTMLLocalResourceError


def _entry_failure(
    entry: PurePosixPath,
    error: Exception,
) -> ProjectInspection:
    return ProjectInspection(
        documents=(),
        inputs=VanillaSourceGraph.inputs_for(entry),
        diagnostics=(
            ProjectDiagnostic(
                code="entry-document-invalid",
                severity="error",
                message=str(error),
                hint="Restore the HTML entry document and build the view again.",
            ),
        ),
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


class VanillaProvider:
    """Inspect and build browser-native view projects."""

    info = ProviderInfo(
        title="Vanilla web",
        summary="Publishes HTML with optional local CSS and JavaScript.",
        options=frozenset({"entrypoint"}),
    )

    def availability(self) -> ProviderAvailability:
        return ProviderAvailability(True)

    def starters(self) -> tuple[ProviderStarter, ...]:
        return tuple(starter.info for starter in STARTERS)

    def create(self, starter: ProviderStarter, context: StarterContext) -> StarterPlan:
        return create_starter(STARTERS, starter, context)

    def inspect(self, request: InspectionRequest) -> ProjectInspection:
        project = request.project
        entry_path = vanilla_entry_path(project)
        try:
            entry = vanilla_entry_document(project, entry_path)
            source = (
                FileTree(project.root)
                .read(project.root.joinpath(*entry_path.parts))
                .content
            )
        except (ConfigurationError, FileNotFoundError) as error:
            return _entry_failure(entry_path, error)
        sites, site_diagnostics = html_sites(entry_path, source)
        if site_diagnostics:
            return ProjectInspection(
                documents=(entry,),
                inputs=VanillaSourceGraph.inputs_for(entry_path),
                sites=sites,
                diagnostics=site_diagnostics,
            )
        try:
            graph = VanillaSourceGraph.analyze(project, entry)
        except VanillaSourceGraphError as error:
            return ProjectInspection(
                documents=(entry, *error.direct_documents),
                inputs=error.inputs,
                sites=sites,
                diagnostics=(_source_diagnostic(entry_path, error.cause),),
            )
        return ProjectInspection(
            documents=graph.documents,
            inputs=graph.inputs,
            sites=sites,
        )

    def build(self, request: BuildRequest) -> BuildResult:
        source_entry = vanilla_entry_path(request.project)
        entry = vanilla_entry_document(request.project, source_entry)
        try:
            graph = VanillaSourceGraph.analyze(
                request.project,
                entry,
                available_inputs=request.inputs,
            )
        except VanillaSourceGraphError as error:
            raise error.cause from error
        for relative in graph.source_paths:
            request.cancellation.raise_if_cancelled("The Vanilla build")
            source = request.project.root.joinpath(*relative.parts)
            destination = request.staging_root.joinpath(*relative.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        request.cancellation.raise_if_cancelled("The Vanilla build")
        document = request.staging_root.joinpath(*source_entry.parts)
        document.write_bytes(graph.with_source_revisions().encode("utf-8"))
        return BuildResult(source_entry, ())


provider = VanillaProvider()
