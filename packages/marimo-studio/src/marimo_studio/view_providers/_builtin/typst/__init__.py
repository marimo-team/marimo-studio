"""Render Typst documents with notebook values, outputs, and cells.

Authors read notebook values in Typst with
``marimo_value("selector", default: ...)``, place rendered outputs such as
figures with ``marimo_output("selector", width: ...)``, and place a named
cell's output with ``marimo_cell("name")``, all from the project's
``marimo.typ``. The build measures the size the document places each output
at and publishes the project as a private template. Studio renders it to PDF
with ``render()`` once without values, then again whenever a reader's values
change. The compile runs in a child process with embedded and project fonts
only, so a document renders the same way on every machine and a stuck compile
can be stopped.

Studio delivers each output as an image in the first of ``IMAGE_TYPES`` the
value supports, drawn at its measured size, so a matplotlib figure arrives as a
PDF whose text keeps its point size. A cell arrives as marimo shows it,
when that is one of those images. The render writes images beneath
``/.marimo-studio`` in its copy of the template. ``marimo.typ`` reads the values
and image paths from ``sys.inputs``, so the project also compiles with the
Typst CLI or an editor preview, where every call returns its default.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from importlib import resources
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path, PurePosixPath
from typing import cast

from packaging.version import InvalidVersion, Version

from marimo_studio.view_providers import (
    BuildRequest,
    BuildResult,
    InspectionRequest,
    ProjectDiagnostic,
    ProjectInspection,
    ProviderAvailability,
    ProviderInfo,
    ProviderRunner,
    ProviderStarter,
    RenderRequest,
    Representation,
    Size,
    SourceLocation,
    StarterContext,
    StarterPlan,
    copy_inputs,
    create_starter,
    project_path,
)
from marimo_studio.view_providers._builtin._typeset import (
    TypesetLanguage,
    inspect_typeset,
    write_media,
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
TYPST = TypesetLanguage(
    name="Typst",
    entry=PurePosixPath("main.typ"),
    languages={
        ".bib": "bibtex",
        ".csv": "plaintext",
        ".json": "json",
        ".md": "markdown",
        ".svg": "xml",
        ".toml": "toml",
        ".typ": "typst",
        ".yaml": "yaml",
        ".yml": "yaml",
    },
    sources=frozenset({".typ"}),
    reads=typst_reads,
)


def _compile_diagnostic(
    item: dict[str, object],
    severity: str,
    root: Path,
    document: PurePosixPath,
) -> ProjectDiagnostic:
    message = str(item.get("message") or f"Typst could not compile {document}.").strip()
    path, line, column = item.get("path"), item.get("line"), item.get("column")
    source = None
    if isinstance(path, str) and isinstance(line, int) and isinstance(column, int):
        try:
            relative = project_path(path)
        except ValueError:
            relative = None
        # A diagnostic inside a Typst package names a file outside the view
        # project, so its location stays in the message.
        if relative and root.joinpath(*relative.parts).is_file():
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


def _run_typst(
    runner: ProviderRunner,
    root: Path,
    document: PurePosixPath,
    inputs: Path,
    output: str,
    timeout: float,
) -> dict[str, object] | ProjectDiagnostic:
    """Run ``_compile.py`` and return its report, or the diagnostic it failed with."""
    compiler = resources.files(__name__).joinpath("_compile.py")
    with resources.as_file(compiler) as script:
        completed = runner.run(
            [
                sys.executable,
                # Isolated mode keeps this package's directory off sys.path.
                "-I",
                str(script),
                str(root),
                document.as_posix(),
                str(inputs),
                output,
            ],
            cwd=root,
            timeout=timeout,
        )
    try:
        report = json.loads(completed.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        return ProjectDiagnostic(
            "typst-compile-failed",
            "error",
            " ".join(
                (
                    f"Typst stopped before it finished {document}.",
                    completed.stderr.strip()[-2_000:].strip(),
                )
            ).strip(),
            f"Fix {document}, then save it to render again.",
        )
    if completed.returncode != 0 or "error" in report:
        return _compile_diagnostic(report.get("error", {}), "error", root, document)
    return report


def _output_sizes(records: object) -> dict[str, Size]:
    """Return the widest size the document places each output at."""
    sizes: dict[str, Size] = {}
    for record in records if isinstance(records, list) else ():
        if not isinstance(record, dict) or not isinstance(record.get("target"), str):
            continue
        try:
            size = Size(cast(float, record.get("width")), record.get("height"))
        except (TypeError, ValueError):
            # A slot without width, or one wider than a figure can be drawn,
            # places the output at the size the notebook drew it.
            continue
        target = record["target"]
        if target not in sizes or size.width > sizes[target].width:
            sizes[target] = size
    return sizes


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
        return inspect_typeset(request.project, TYPST)

    def build(self, request: BuildRequest) -> BuildResult:
        entry = TYPST.entrypoint(request.project)
        copy_inputs(request, request.staging_root)
        inputs = request.work_root / "inputs.json"
        inputs.write_text("{}", encoding="utf-8")
        report = _run_typst(
            request.runner,
            request.staging_root,
            entry,
            inputs,
            "--sizes",
            request.command_timeout,
        )
        if isinstance(report, ProjectDiagnostic):
            return BuildResult(None, (report,))
        return BuildResult(entry, output_sizes=_output_sizes(report.get("sizes")))

    def render(self, request: RenderRequest) -> BuildResult:
        root = request.template_root

        def place(media: Mapping[str, Representation]) -> str:
            names = write_media(root.joinpath(*_OUTPUTS.parts), media, IMAGE_TYPES)
            return json.dumps(
                {
                    target: f"/{_OUTPUTS.as_posix()}/{name}"
                    for target, name in names.items()
                }
            )

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
        report = _run_typst(
            request.runner,
            root,
            request.document,
            inputs,
            str(request.output_root.joinpath(*_RENDERED.parts)),
            request.command_timeout,
        )
        if isinstance(report, ProjectDiagnostic):
            return BuildResult(None, (report,))
        warnings = report.get("warnings")
        return BuildResult(
            _RENDERED,
            tuple(
                _compile_diagnostic(item, "warning", root, request.document)
                for item in (warnings if isinstance(warnings, list) else ())
            ),
        )


provider = TypstProvider()
