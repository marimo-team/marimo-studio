"""Render Quarto documents as live Studio views.

The entry document is any file Quarto's markdown engine renders: ``.qmd``,
``.md``, or ``.markdown``. Authors place notebook results with the ``marimo``
shortcode, such as ``{{< marimo cell="summary" >}}``, or with raw HTML
``<marimo-cell>``, ``<marimo-output>``, and ``mo-value`` hosts. Inspection
follows the entry's ``{{< include >}}`` directives the way Quarto resolves
them, and finds the hosts in every document that the render reads.

The build supplies the shortcode as a Quarto extension beside the entry,
renders the snapshot with the installed Quarto CLI, keeps block hosts out of
paragraphs, and wraps the page body in ``#app-shell``. Studio then binds
notebook results into the hosts in the browser, as for any HTML view.

Every project file except ``AGENTS.md`` and ``DESIGN.md`` is a build input, so
images, includes, bibliographies, and stylesheets referenced from the document
rebuild the view when they change.
"""

from __future__ import annotations

import posixpath
from pathlib import PurePosixPath

from marimo_studio.view_providers import (
    BuildInput,
    BuildRequest,
    BuildResult,
    InspectionRequest,
    ProjectDiagnostic,
    ProjectInspection,
    ProjectionSite,
    ProviderAvailability,
    ProviderError,
    ProviderInfo,
    ProviderStarter,
    SourceDocument,
    SourceLocation,
    StarterContext,
    StarterPlan,
    ViewProject,
    create_starter,
    project_files,
)
from marimo_studio.view_providers._builtin.quarto._render import (
    build_quarto,
    quarto_availability,
)
from marimo_studio.view_providers._builtin.quarto._sources import (
    quarto_includes,
    quarto_sites,
)
from marimo_studio.view_providers._builtin.quarto.starters import STARTERS

_OUTPUT_ROOTS = frozenset({"_site", "_freeze"})
# The extensions Quarto's markdown engine renders.
_DOCUMENTS = (".qmd", ".md", ".markdown")
_PROJECT_FILES = ("_quarto.yml", "_quarto.yaml")


def _entry(project: ViewProject) -> PurePosixPath:
    """Return the entry document from ``view.toml``."""
    entry = project.path_option("entrypoint", default="index.qmd")
    if entry.suffix.lower() not in _DOCUMENTS:
        raise ProviderError(
            f"view.toml option 'entrypoint' names {entry}, which Quarto does not "
            "render as Markdown.",
            hint="Set entrypoint to a .qmd, .md, or .markdown document.",
            source=SourceLocation(PurePosixPath("view.toml"), 1, 1),
            code="provider-options-invalid",
        )
    return entry


def _include_root(project: ViewProject, entry: PurePosixPath) -> PurePosixPath:
    """Return the directory that a root-relative include resolves against.

    That is the Quarto project directory, the nearest ancestor of the entry
    with ``_quarto.yml``, or the entry's own directory for a single document.
    """
    for directory in (entry.parent, *entry.parent.parents):
        if any(
            project.root.joinpath(*directory.parts, name).is_file()
            for name in _PROJECT_FILES
        ):
            return directory
    return entry.parent


def _rendered_documents(
    project: ViewProject,
    entry: PurePosixPath,
    files: tuple[PurePosixPath, ...],
) -> tuple[list[PurePosixPath], list[ProjectDiagnostic]]:
    """Return the entry and every document its includes read, in order.

    Quarto resolves an include path against the entry's directory, also inside
    nested includes, and a path that starts with ``/`` against the project
    directory.
    """
    root = _include_root(project, entry)
    documents = [entry]
    diagnostics: list[ProjectDiagnostic] = []
    pending = [entry]
    while pending:
        document = pending.pop(0)
        source = project.root.joinpath(*document.parts).read_bytes()
        for target, line, column in quarto_includes(document, source):
            base = root if target.startswith("/") else entry.parent
            resolved = PurePosixPath(
                posixpath.normpath(posixpath.join(base.as_posix(), target.lstrip("/")))
            )
            location = SourceLocation(document, line, column)
            if resolved.parts[:1] == ("..",):
                diagnostics.append(
                    ProjectDiagnostic(
                        "build-input-invalid",
                        "error",
                        f"{document} includes {target}, outside the view project.",
                        "Move the included file into the view project.",
                        location,
                    )
                )
            elif resolved not in files:
                diagnostics.append(
                    ProjectDiagnostic(
                        "build-input-missing",
                        "error",
                        f"{document} includes {target}, which is missing.",
                        "Create the file or fix the include path. Quarto resolves "
                        "relative includes from the entry document's directory.",
                        location,
                    )
                )
            elif resolved not in documents:
                documents.append(resolved)
                pending.append(resolved)
    return documents, diagnostics


_LANGUAGES = {
    ".bib": "bibtex",
    ".css": "css",
    ".html": "html",
    ".js": "javascript",
    ".json": "json",
    ".lua": "lua",
    ".markdown": "markdown",
    ".md": "markdown",
    ".qmd": "markdown",
    ".scss": "scss",
    ".svg": "xml",
    ".yaml": "yaml",
    ".yml": "yaml",
}


class QuartoProvider:
    """Inspect Quarto Markdown and render it to one live HTML view."""

    info = ProviderInfo(
        title="Quarto",
        summary="Renders a Quarto document with live notebook results.",
        options=frozenset({"entrypoint"}),
    )

    def availability(self) -> ProviderAvailability:
        return quarto_availability()

    def starters(self) -> tuple[ProviderStarter, ...]:
        return tuple(starter.info for starter in STARTERS)

    def create(self, starter: ProviderStarter, context: StarterContext) -> StarterPlan:
        return create_starter(STARTERS, starter, context)

    def inspect(self, request: InspectionRequest) -> ProjectInspection:
        project = request.project
        entry = _entry(project)
        # Quarto writes rendered output into these directories, and the entry
        # document's figures beside it in `<stem>_files`.
        generated = entry.parent / f"{entry.stem}_files"
        files = tuple(
            path
            for path in project_files(
                project, exclude={*_OUTPUT_ROOTS, f"{entry.stem}_files"}
            )
            if not path.is_relative_to(generated)
        )
        documents = tuple(
            SourceDocument(path, _LANGUAGES[path.suffix.lower()], "edit")
            for path in files
            if path.suffix.lower() in _LANGUAGES
        )
        inputs = tuple(BuildInput(path, "file") for path in files)
        if entry not in files:
            return ProjectInspection(
                documents,
                inputs,
                diagnostics=(
                    ProjectDiagnostic(
                        "build-input-missing",
                        "error",
                        f"Quarto entry document {entry} is missing.",
                        "Restore the entry document or set entrypoint in view.toml.",
                    ),
                ),
            )
        rendered, diagnostics = _rendered_documents(project, entry, files)
        sites: list[ProjectionSite] = []
        for path in rendered:
            found, problems = quarto_sites(
                path,
                project.root.joinpath(*path.parts).read_bytes(),
            )
            sites.extend(found)
            diagnostics.extend(problems)
        return ProjectInspection(
            documents,
            inputs,
            sites=tuple(sites),
            diagnostics=tuple(diagnostics),
        )

    def build(self, request: BuildRequest) -> BuildResult:
        return build_quarto(request, _entry(request.project))


provider = QuartoProvider()
