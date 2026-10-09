"""Inspect typeset document projects and place the media their renders read.

Typst and LaTeX views share one shape: a project of text sources with one entry
document, whose sources read notebook values, outputs, and cells through calls
that a language scanner finds. ``inspect_typeset()`` lists the project's Source
documents and build inputs and collects those reads. A render finds the same
reads in its template with ``template_reads()``, writes each output and cell it
receives with ``write_media()``, and compiles the entry.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from marimo_studio.view_providers import (
    BuildInput,
    ProjectDiagnostic,
    ProjectInspection,
    RenderCell,
    RenderOutput,
    RenderValue,
    Representation,
    SourceDocument,
    SourceLocation,
    ViewProject,
    project_files,
)


@dataclass(frozen=True)
class DocumentReads:
    """The notebook values, outputs, and cells that one source file reads."""

    values: tuple[RenderValue, ...] = ()
    outputs: tuple[RenderOutput, ...] = ()
    cells: tuple[RenderCell, ...] = ()


@dataclass(frozen=True)
class TypesetLanguage:
    """Describe one typesetting language's view projects.

    ``entry`` is the default ``entrypoint`` option, and its suffix is the one
    every entry document must have. ``languages`` maps the file suffixes shown
    in Source to their editor language. ``reads`` scans one source file whose
    suffix is in ``sources``.
    """

    name: str
    entry: PurePosixPath
    languages: Mapping[str, str]
    sources: frozenset[str]
    reads: Callable[[PurePosixPath, str], DocumentReads]

    def entrypoint(self, project: ViewProject) -> PurePosixPath:
        """Return the entry document that ``view.toml`` selects."""
        return project.path_option(
            "entrypoint",
            default=self.entry.as_posix(),
            suffix=self.entry.suffix,
        )


def inspect_typeset(
    project: ViewProject, language: TypesetLanguage
) -> ProjectInspection:
    """Describe a typeset project: its documents, inputs, and notebook reads.

    Every project file is a build input. Source shows the files whose suffix
    the language edits, and every source file is scanned for reads.
    """
    entry = language.entrypoint(project)
    files = project_files(project)
    documents = tuple(
        SourceDocument(path, language.languages[path.suffix.lower()], "edit")
        for path in files
        if path.suffix.lower() in language.languages
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
                    f"{language.name} entry document {entry} is missing.",
                    "Restore the entry document or set entrypoint in view.toml.",
                ),
            ),
        )
    values: list[RenderValue] = []
    outputs: list[RenderOutput] = []
    cells: list[RenderCell] = []
    diagnostics: list[ProjectDiagnostic] = []
    for path in files:
        if path.suffix.lower() not in language.sources:
            continue
        try:
            source = project.root.joinpath(*path.parts).read_bytes().decode()
        except UnicodeDecodeError:
            diagnostics.append(
                ProjectDiagnostic(
                    "source-document-invalid",
                    "error",
                    f"{path} must be UTF-8 text.",
                    source=SourceLocation(path, 1, 1),
                )
            )
            continue
        reads = language.reads(path, source)
        values.extend(reads.values)
        outputs.extend(reads.outputs)
        cells.extend(reads.cells)
    return ProjectInspection(
        documents,
        inputs,
        diagnostics=tuple(diagnostics),
        render_values=tuple(values),
        render_outputs=tuple(outputs),
        render_cells=tuple(cells),
    )


def template_reads(root: Path, language: TypesetLanguage) -> DocumentReads:
    """Return the reads of every source file in a rendered template.

    A template holds the build's inputs, which Studio already inspected, so
    every source file reads as UTF-8 text.
    """
    values: list[RenderValue] = []
    outputs: list[RenderOutput] = []
    cells: list[RenderCell] = []
    for path in sorted(root.rglob("*")):
        relative = PurePosixPath(path.relative_to(root).as_posix())
        if (
            path.suffix.lower() not in language.sources
            or relative.parts[0].startswith(".")
            or not path.is_file()
        ):
            continue
        reads = language.reads(relative, path.read_text(encoding="utf-8"))
        values.extend(reads.values)
        outputs.extend(reads.outputs)
        cells.extend(reads.cells)
    return DocumentReads(tuple(values), tuple(outputs), tuple(cells))


def write_media(
    directory: Path,
    media: Mapping[str, Representation],
    extensions: Mapping[str, str],
) -> dict[str, str]:
    """Write each image beneath ``directory`` and return its file name by target.

    A file is named by its content digest and the extension ``extensions``
    gives its media type, so identical images share one file.
    """
    names: dict[str, str] = {}
    for target, item in media.items():
        name = f"{hashlib.sha256(item.data).hexdigest()}.{extensions[item.media_type]}"
        directory.mkdir(parents=True, exist_ok=True)
        directory.joinpath(name).write_bytes(item.data)
        names[target] = name
    return names
