"""Render Typst documents with notebook values, outputs, and cells.

Authors read notebook values in Typst with
``marimo_value("selector", default: ...)``, place rendered outputs such as
figures with ``marimo_output("selector", width: ...)``, and place a named
cell's output with ``marimo_cell("name")``, all from the project's
``marimo.typ``. The build publishes the project as a private template. Studio
renders it to PDF with ``render()`` once without values, then again whenever a
reader's values change. The compile runs in a child process with embedded and
project fonts only, so a document renders the same way on every machine and a
stuck compile can be stopped.

Studio delivers each output as an image in the first of ``IMAGE_TYPES`` the
value supports, so a matplotlib figure arrives as a PDF with selectable text
whatever the notebook's own output settings. A cell arrives as marimo shows it,
when that is one of those images. The render writes images beneath
``/.marimo-studio`` in its copy of the template. ``marimo.typ`` reads the values
and image paths from ``sys.inputs``, so the project also compiles with the
Typst CLI or an editor preview, where every call returns its default.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Mapping
from importlib import resources
from importlib.metadata import PackageNotFoundError, version
from pathlib import PurePosixPath

from packaging.version import InvalidVersion, Version

from marimo_studio.view_providers import (
    BuildInput,
    BuildRequest,
    BuildResult,
    InspectionRequest,
    ProjectDiagnostic,
    ProjectInspection,
    ProviderAvailability,
    ProviderInfo,
    ProviderStarter,
    RenderCell,
    RenderOutput,
    RenderRequest,
    RenderValue,
    Representation,
    SourceDocument,
    SourceLocation,
    StarterContext,
    StarterPlan,
    copy_inputs,
    create_starter,
    project_files,
    project_path,
)
from marimo_studio.view_providers._builtin.typst._sources import (
    IMAGE_TYPES,
    typst_reads,
)
from marimo_studio.view_providers._builtin.typst.starters import STARTERS

TYPST_MIN_VERSION = "0.15"
INSTALL_ACTION = (
    "Install marimo-studio[typst] in the Python environment that runs Studio."
)
_RENDERED = PurePosixPath("document.pdf")
_OUTPUTS = PurePosixPath(".marimo-studio/outputs")
_LANGUAGES = {
    ".bib": "bibtex",
    ".csv": "plaintext",
    ".json": "json",
    ".md": "markdown",
    ".svg": "xml",
    ".toml": "toml",
    ".typ": "typst",
    ".yaml": "yaml",
    ".yml": "yaml",
}


def _compile_diagnostic(
    item: dict[str, object],
    severity: str,
    request: RenderRequest,
) -> ProjectDiagnostic:
    message = str(
        item.get("message") or f"Typst could not compile {request.document}."
    ).strip()
    path, line, column = item.get("path"), item.get("line"), item.get("column")
    source = None
    if isinstance(path, str) and isinstance(line, int) and isinstance(column, int):
        try:
            relative = project_path(path)
        except ValueError:
            relative = None
        # A diagnostic inside a Typst package names a file outside the view
        # project, so its location stays in the message.
        if relative and request.template_root.joinpath(*relative.parts).is_file():
            source = SourceLocation(relative, line, column)
        else:
            message = f"{path}:{line}:{column}: {message}"
    hints = item.get("hints")
    return ProjectDiagnostic(
        code="typst-compile-error" if severity == "error" else "typst-compile-warning",
        severity="error" if severity == "error" else "warning",
        message=message,
        hint=" ".join(str(hint) for hint in hints) if isinstance(hints, list) else "",
        source=source,
    )


class TypstProvider:
    """Inspect Typst source and render it to PDF with notebook values."""

    info = ProviderInfo(
        title="Typst",
        summary="Renders a Typst document to PDF with live notebook values.",
        options=frozenset({"entrypoint"}),
    )

    def availability(self) -> ProviderAvailability:
        try:
            installed = version("typst")
        except PackageNotFoundError:
            return ProviderAvailability(
                False,
                reason="The typst Python package is not installed.",
                action=INSTALL_ACTION,
            )
        try:
            supported = Version(installed) >= Version(TYPST_MIN_VERSION)
        except InvalidVersion:
            supported = False
        if not supported:
            return ProviderAvailability(
                False,
                version=installed,
                reason=f"typst {installed} is older than {TYPST_MIN_VERSION}.",
                action=INSTALL_ACTION,
            )
        return ProviderAvailability(True, version=installed)

    def starters(self) -> tuple[ProviderStarter, ...]:
        return tuple(starter.info for starter in STARTERS)

    def create(self, starter: ProviderStarter, context: StarterContext) -> StarterPlan:
        return create_starter(STARTERS, starter, context)

    def inspect(self, request: InspectionRequest) -> ProjectInspection:
        project = request.project
        entry = project.path_option("entrypoint", default="main.typ", suffix=".typ")
        files = project_files(project)
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
                        f"Typst entry document {entry} is missing.",
                        "Restore the entry document or set entrypoint in view.toml.",
                    ),
                ),
            )
        values: list[RenderValue] = []
        outputs: list[RenderOutput] = []
        cells: list[RenderCell] = []
        diagnostics: list[ProjectDiagnostic] = []
        for path in files:
            if path.suffix.lower() != ".typ":
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
            file_values, file_outputs, file_cells = typst_reads(path, source)
            values.extend(file_values)
            outputs.extend(file_outputs)
            cells.extend(file_cells)
        return ProjectInspection(
            documents,
            inputs,
            diagnostics=tuple(diagnostics),
            render_values=tuple(values),
            render_outputs=tuple(outputs),
            render_cells=tuple(cells),
        )

    def build(self, request: BuildRequest) -> BuildResult:
        copy_inputs(request, request.staging_root)
        return BuildResult(
            request.project.path_option("entrypoint", default="main.typ", suffix=".typ")
        )

    def render(self, request: RenderRequest) -> BuildResult:
        root = request.template_root

        def place(media: Mapping[str, Representation]) -> str:
            paths: dict[str, str] = {}
            for target, item in media.items():
                digest = hashlib.sha256(item.data).hexdigest()
                name = f"{digest}.{IMAGE_TYPES[item.media_type]}"
                root.joinpath(*_OUTPUTS.parts).mkdir(parents=True, exist_ok=True)
                root.joinpath(*_OUTPUTS.parts, name).write_bytes(item.data)
                paths[target] = f"/{_OUTPUTS.as_posix()}/{name}"
            return json.dumps(paths)

        inputs = request.output_root / "inputs.json"
        inputs.write_text(
            json.dumps(
                {
                    "marimo-values": json.dumps(
                        dict(request.values), ensure_ascii=False
                    ),
                    "marimo-outputs": place(request.outputs),
                    "marimo-cells": place(request.cells),
                }
            ),
            encoding="utf-8",
        )
        compiler = resources.files(__name__).joinpath("_compile.py")
        with resources.as_file(compiler) as script:
            completed = request.runner.run(
                [
                    sys.executable,
                    # Isolated mode keeps this package's directory off sys.path.
                    "-I",
                    str(script),
                    str(root),
                    request.document.as_posix(),
                    str(inputs),
                    str(request.output_root.joinpath(*_RENDERED.parts)),
                ],
                cwd=root,
                timeout=request.command_timeout,
            )
        try:
            report = json.loads(completed.stdout.strip().splitlines()[-1])
        except (IndexError, json.JSONDecodeError):
            return BuildResult(
                None,
                (
                    ProjectDiagnostic(
                        "typst-compile-failed",
                        "error",
                        " ".join(
                            (
                                f"Typst stopped before it finished {request.document}.",
                                completed.stderr.strip()[-2_000:].strip(),
                            )
                        ).strip(),
                        f"Fix {request.document}, then save it to render again.",
                    ),
                ),
            )
        if completed.returncode != 0 or "error" in report:
            return BuildResult(
                None,
                (_compile_diagnostic(report.get("error", {}), "error", request),),
            )
        return BuildResult(
            _RENDERED,
            tuple(
                _compile_diagnostic(item, "warning", request)
                for item in report.get("warnings", [])
            ),
        )


provider = TypstProvider()
