"""Render LaTeX documents with notebook values, outputs, and cells.

Authors load the project's ``marimo.sty`` with ``\\usepackage{marimo}``. They
typeset a notebook value with ``\\marimovalue{selector}``, format numbers and
dates with ``\\marimonum`` and ``\\marimodate``, branch with ``\\IfMarimoTF``,
and repeat a table row for each item of a list or table with ``\\marimorows``.
``\\marimographics[width=...]{selector}`` places a figure, and
``\\marimocell{name}`` places a named cell's output. The build compiles the
project once, which measures the size the document places each figure at, and
publishes it as a private template. Studio renders it to PDF with ``render()``
once without values, then again whenever a reader's values change.

Studio delivers each output as an image in the first of ``IMAGE_TYPES`` the
value supports, drawn at its measured size, so a matplotlib figure arrives as
a PDF whose text keeps its point size. A render writes the images and an
``inputs.tex`` file that defines every read beneath ``.marimo-studio`` beside
the entry document, and ``marimo.sty`` loads that file when it exists. The
project therefore also compiles with Tectonic, latexmk, or an editor preview,
where every read typesets its fallback.
"""

from __future__ import annotations

from pathlib import PurePosixPath

from marimo_studio.view_providers import (
    BuildRequest,
    BuildResult,
    InspectionRequest,
    ProjectDiagnostic,
    ProjectInspection,
    ProviderAvailability,
    ProviderCommandError,
    ProviderInfo,
    ProviderStarter,
    RenderRequest,
    SourceLocation,
    StarterContext,
    StarterPlan,
    copy_inputs,
    create_starter,
)
from marimo_studio.view_providers._builtin._typeset import (
    TypesetLanguage,
    inspect_typeset,
    template_reads,
    write_media,
)
from marimo_studio.view_providers._builtin.latex._inputs import (
    MAX_INPUT_DEFINITIONS,
    InputsTooLarge,
    render_inputs,
)
from marimo_studio.view_providers._builtin.latex._sources import (
    IMAGE_TYPES,
    LANGUAGES,
    latex_reads,
)
from marimo_studio.view_providers._builtin.latex._tectonic import (
    compile_latex,
    tectonic_availability,
)
from marimo_studio.view_providers._builtin.latex.starters import STARTERS

_INPUTS = PurePosixPath(".marimo-studio")
LATEX = TypesetLanguage(
    name="LaTeX",
    entry=PurePosixPath("main.tex"),
    languages=LANGUAGES,
    sources=frozenset({".tex"}),
    reads=latex_reads,
)


class LatexProvider:
    """Inspect LaTeX source and render it to PDF with notebook values."""

    info = ProviderInfo(
        title="LaTeX",
        summary="Typesets a LaTeX document to PDF with live notebook values.",
        options=frozenset({"entrypoint"}),
    )

    def availability(self) -> ProviderAvailability:
        return tectonic_availability()

    def starters(self) -> tuple[ProviderStarter, ...]:
        return tuple(starter.info for starter in STARTERS)

    def create(self, starter: ProviderStarter, context: StarterContext) -> StarterPlan:
        return create_starter(STARTERS, starter, context)

    def inspect(self, request: InspectionRequest) -> ProjectInspection:
        return inspect_typeset(request.project, LATEX)

    def build(self, request: BuildRequest) -> BuildResult:
        entry = LATEX.entrypoint(request.project)
        copy_inputs(request, request.staging_root)
        # Compile once under the build's command budget, which outlasts a
        # render's. Tectonic downloads the packages a document uses on its
        # first compile, so later renders find them cached.
        try:
            compiled = compile_latex(
                request.runner,
                request.staging_root,
                entry,
                request.work_root,
                request.command_timeout,
            )
        except ProviderCommandError as error:
            request.cancellation.raise_if_cancelled("The LaTeX build")
            # The runner reports a command that outlasted its time as exceeded.
            if "exceeded" not in str(error):
                raise
            return BuildResult(
                None,
                (
                    ProjectDiagnostic(
                        "latex-compile-unfinished",
                        "error",
                        f"Tectonic did not finish compiling {entry}: {error}.",
                        "A first compile downloads the TeX packages the document "
                        "uses and keeps them, so building the view again continues. "
                        f"Run `tectonic -X compile {entry.name}` in the view folder "
                        "to download them without a time limit. A document that "
                        "never finishes compiling, such as one with a recursive "
                        "macro, also ends this way.",
                        SourceLocation(entry, 1, 1),
                    ),
                ),
            )
        if compiled.document is None:
            return compiled
        return BuildResult(entry, output_sizes=compiled.output_sizes)

    def render(self, request: RenderRequest) -> BuildResult:
        base = request.template_root.joinpath(*request.document.parent.parts)
        inputs = base.joinpath(*_INPUTS.parts)
        outputs = inputs / "outputs"

        def paths(names: dict[str, str]) -> dict[str, str]:
            return {
                target: f"{_INPUTS.as_posix()}/outputs/{name}"
                for target, name in names.items()
            }

        try:
            text = render_inputs(
                request.values,
                paths(write_media(outputs, request.outputs, IMAGE_TYPES)),
                paths(write_media(outputs, request.cells, IMAGE_TYPES)),
                template_reads(request.template_root, LATEX),
            )
        except InputsTooLarge:
            return BuildResult(
                None,
                (
                    ProjectDiagnostic(
                        "latex-values-too-large",
                        "error",
                        "The notebook values this document reads need more than "
                        f"{MAX_INPUT_DEFINITIONS:,} LaTeX definitions.",
                        "Read the fields the document places, such as summary.total, "
                        "or project a table to the rows it shows.",
                    ),
                ),
            )
        inputs.mkdir(parents=True, exist_ok=True)
        inputs.joinpath("inputs.tex").write_text(text, encoding="utf-8")
        compiled = compile_latex(
            request.runner,
            request.template_root,
            request.document,
            request.output_root,
            request.command_timeout,
        )
        return BuildResult(compiled.document, compiled.diagnostics)


provider = LatexProvider()
