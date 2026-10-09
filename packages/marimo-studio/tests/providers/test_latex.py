from __future__ import annotations

import io
import time
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path, PurePosixPath

import pytest
from marimo_export.values import represent

from marimo_studio._artifacts.repository import read_profile_state
from marimo_studio._processes.provider_runner import (
    ProviderCommandError,
    create_provider_runner,
)
from marimo_studio._views.build import build_view_project_sync
from marimo_studio._views.inspection import inspect_view_project_sync
from marimo_studio._workspace.project_manifest import (
    encode_view_manifest,
    load_view_project,
)
from marimo_studio.errors import ViewProjectError
from marimo_studio.view_providers import (
    BuildResult,
    JsonValue,
    ProviderCancellation,
    ProviderCommandResult,
    ProviderError,
    ProviderRunner,
    RenderCell,
    RenderOutput,
    RenderRequest,
    RenderValue,
    Representation,
    Size,
    SourceLocation,
    ViewProject,
)
from marimo_studio.view_providers._builtin._typeset import DocumentReads
from marimo_studio.view_providers._builtin.latex import _inputs, provider
from marimo_studio.view_providers._builtin.latex._inputs import (
    _SYMBOLS,
    latex_text,
    render_inputs,
)

from ..provider_test_support import (
    provider_build_request,
    provider_starter_context,
    publish,
)

MAIN = PurePosixPath("main.tex")
# Fails the compile, so a render reports whether a condition held.
EXPECT = r"\newcommand\expect[2]{#1\else\PackageError{expect}{#2}{}\fi}"
tectonic = pytest.mark.skipif(
    not provider.availability().available,
    reason="Tectonic is unavailable",
)


def _project(tmp_path: Path, main: str | None = None) -> ViewProject:
    plan = provider.create(
        provider.starters()[0],
        provider_starter_context(tmp_path, view_name="paper"),
    )
    root = tmp_path / "paper"
    for relative, content in plan.files.items():
        path = root.joinpath(*relative.parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    (root / "view.toml").write_text(
        encode_view_manifest("marimo-studio/latex"),
        encoding="utf-8",
    )
    if main is not None:
        (root / MAIN).write_text(main, encoding="utf-8")
    return load_view_project(root)


def _document(body: str, preamble: str = "") -> str:
    return (
        "\\documentclass{article}\n"
        f"{preamble}"
        "\\usepackage{marimo}\n"
        f"{EXPECT}\n"
        "\\begin{document}\n"
        f"{body}\n"
        "\\end{document}\n"
    )


def _render(
    project: ViewProject,
    values: Mapping[str, JsonValue],
    *,
    outputs: Mapping[str, Representation] | None = None,
    cells: Mapping[str, Representation] | None = None,
    runner: ProviderRunner | None = None,
    timeout: float = 60.0,
    document: PurePosixPath = MAIN,
):
    output = project.root.parent / f"output-{time.monotonic_ns()}"
    output.mkdir()
    cancellation = ProviderCancellation()
    return output, provider.render(
        RenderRequest(
            template_root=project.root,
            document=document,
            values=values,
            outputs=outputs or {},
            cells=cells or {},
            output_root=output,
            cancellation=cancellation,
            runner=runner
            or create_provider_runner(project.root, cancellation, timeout),
            command_timeout=timeout,
        )
    )


def test_latex_reads_literal_selectors_outside_comments_and_verbatim(
    tmp_path: Path,
) -> None:
    project = _project(
        tmp_path,
        "\\documentclass{article}\n"
        "\\usepackage{marimo}\n"
        "\\begin{document}\n"
        "% \\marimovalue{commented}\n"
        "Rooms: \\marimovalue[--]{summary.rooms} and 50\\% "
        '\\marimovalue{rows[0]["name"]}.\n'
        "\\verb|\\marimovalue{verb}| \\IfMarimoTF{flag}{yes}{no}\n"
        "\\begin{verbatim}\n\\marimovalue{verbatim}\n\\end{verbatim}\n"
        "\\begin{tabular}{l}\n"
        "\\marimorows[3]{sensors}{\\marimovalue{#1.label} \\\\}\n"
        "\\end{tabular}\n"
        "\\marimovalueextra{not-a-read}\n"
        "\\marimographics[width=0.5\\linewidth, alt={A [bracket]}]{charts.sweep}\n"
        "\\marimocell{revenue_plot}\n"
        "\\marimonum[share]{model.accuracy} \\marimodate{period.start}\n"
        "\\marimoforeach{days}{\\marimotime{#1.start}} \\IfMarimoF{peak}{none}\n"
        "\\end{document}\n",
    )

    inspection = inspect_view_project_sync(project)

    assert inspection.diagnostics == ()
    assert [(item.target, item.source) for item in inspection.render_values] == [
        ("summary.rooms", SourceLocation(MAIN, 5, 8)),
        ('rows[0]["name"]', SourceLocation(MAIN, 5, 49)),
        ("flag", SourceLocation(MAIN, 6, 27)),
        ("sensors", SourceLocation(MAIN, 11, 1)),
        ("model.accuracy", SourceLocation(MAIN, 16, 1)),
        ("period.start", SourceLocation(MAIN, 16, 35)),
        ("days", SourceLocation(MAIN, 17, 1)),
        ("peak", SourceLocation(MAIN, 17, 45)),
    ]
    (output,) = inspection.render_outputs
    assert (output.target, output.source) == (
        "charts.sweep",
        SourceLocation(MAIN, 14, 1),
    )
    assert output.accept == ("application/pdf", "image/png", "image/jpeg")
    (cell,) = inspection.render_cells
    assert (cell.target, cell.source) == ("revenue_plot", SourceLocation(MAIN, 15, 1))
    assert {item.path.as_posix() for item in inspection.documents} == {
        "AGENTS.md",
        "main.tex",
        "marimo.sty",
    }
    assert PurePosixPath("AGENTS.md") not in {item.path for item in inspection.inputs}


def test_verbatim_arguments_neither_hide_nor_add_reads(tmp_path: Path) -> None:
    project = _project(
        tmp_path,
        _document(
            "\\lstinline{x = \\marimovalue{code}} gives \\marimovalue{after.code}\n"
            "\\url{https://example.org/a%20b} for \\marimovalue{after.url}\n"
            "\\href{https://example.org/50%}{\\marimovalue{link.text}}\n"
            "\\href{\\marimovalue{link.url}}{data}"
        ),
    )

    inspection = inspect_view_project_sync(project)

    assert [item.target for item in inspection.render_values] == [
        "after.code",
        "after.url",
        "link.text",
        "link.url",
    ]


def test_invalid_value_selectors_are_reported_at_their_command(tmp_path: Path) -> None:
    project = _project(tmp_path, _document("\\marimovalue{rows..}"))

    (diagnostic,) = inspect_view_project_sync(project).diagnostics

    assert diagnostic.code == "render-value-invalid"
    assert diagnostic.source == SourceLocation(MAIN, 5, 1)


def test_a_missing_entry_document_is_reported(tmp_path: Path) -> None:
    project = _project(tmp_path)
    project.root.joinpath(MAIN).unlink()

    (diagnostic,) = inspect_view_project_sync(project).diagnostics

    assert diagnostic.code == "build-input-missing"
    assert diagnostic.message == "LaTeX entry document main.tex is missing."


@pytest.mark.parametrize(
    ("text", "latex"),
    (
        (
            "50% of $x_1 & {y}^2 #3 ~ \\",
            r"50\% of \$x\_1 \& \{y\}\textasciicircum 2 \#3 \textasciitilde{} "
            r"\textbackslash{}",
        ),
        ("<a|b>", r"\textless a\textbar b\textgreater{}"),
        (
            "Weekdays \u00b7 07:00\u201319:00",
            r"Weekdays \textperiodcentered{} 07:00\textendash 19:00",
        ),
        (
            "21.5 °C ± 0.4, 5 µs, ≥ 3",
            r"21.5 \textdegree C \textpm{} 0.4, 5 \textmu s, "
            "\\texorpdfstring{\\ensuremath{\\geq}}{\u2265} 3",
        ),
        ("café Ångström Łódź ő", r"caf\'{e} \r{A}ngstr\"{o}m \L \'{o}d\'{z} \H{o}"),
        (
            "\u201cquoted\u201d \u2014 \u03b1",
            r"\textquotedblleft quoted\textquotedblright{} \textemdash{} "
            "\\texorpdfstring{\\ensuremath{\\alpha}}{\u03b1}",
        ),
        ("--flag a---b '' ``", "-{}-flag a-{}-{}-b '{}' `{}`"),
        (
            '1\u00ba \u00a4 "q" \u0110 \u0219ir',
            r"1\textordmasculine{} \textcurrency{} \textquotedbl q\textquotedbl{} "
            r"\DJ{} \textcommabelow{s}ir",
        ),
        ("line\nbreak\tand\x07bell", "line break andbell"),
        ("zero\u200bwidth\ufeff and\u2028line", "zerowidth and line"),
        ("https://example.org/a_b~c/d", r"https://example.org/a\_b\textasciitilde c/d"),
        ("漢字", "漢字"),
    ),
)
def test_notebook_text_becomes_latex_for_t1_and_unicode_fonts(
    text: str, latex: str
) -> None:
    assert latex_text(text) == latex


def test_long_text_wraps_into_lines_that_tex_joins_back() -> None:
    words = " ".join(["word"] * 2_000)
    run = "x" * 9_000

    text = latex_text(f"{words} {run}")

    assert max(len(line) for line in text.split("\n")) <= 4_001
    assert text.replace("%\n", "").replace("\n", " ") == f"{words} {run}"


def test_render_inputs_define_every_value_by_its_selector_and_type() -> None:
    here = SourceLocation(MAIN, 1, 1)
    inputs = render_inputs(
        {
            "report": {
                "title": "Q3",
                "total": 7,
                "share": 0.25,
                "late": False,
                "missing": None,
                "rows": [{"day": "2015-02-04", "at": "2015-02-04T09:41:00+01:00"}],
                "odd key": 1,
                "_private": 2,
                "bad%key": 3,
            },
        },
        {"chart": ".marimo-studio/outputs/a.pdf"},
        {"plot": ".marimo-studio/outputs/b.png"},
        DocumentReads(
            (RenderValue("report", here), RenderValue("absent", here)),
            (
                RenderOutput("chart", here, ("application/pdf",)),
                RenderOutput("pending", here, ("application/pdf",)),
            ),
            (RenderCell("plot", here, ("image/png",)), RenderCell("blank", here, ())),
        ),
    )

    (version, *definitions) = inputs.splitlines()
    assert version == "\\marimo@inputs{2}"
    assert sorted(definitions) == sorted(
        [
            "\\marimo@d{report}{9}",
            "\\marimo@s{report.title}{Q3}",
            "\\marimo@n{report.total}{7}",
            "\\marimo@n{report.share}{0.25}",
            "\\marimo@b{report.late}{0}",
            "\\marimo@z{report.missing}",
            "\\marimo@l{report.rows}{1}",
            "\\marimo@d{report.rows[0]}{2}",
            "\\marimo@s{report.rows[0].day}{2015-02-04}",
            "\\marimo@t{report.rows[0].day}{2015-02-04}{}",
            "\\marimo@s{report.rows[0].at}{2015-02-04T09:41:00+01:00}",
            "\\marimo@t{report.rows[0].at}{2015-02-04}{09:41:00}",
            '\\marimo@n{report["odd key"]}{1}',
            '\\marimo@n{report["_private"]}{2}',
            "\\marimo@g{chart}{.marimo-studio/outputs/a.pdf}",
            "\\marimo@c{plot}{.marimo-studio/outputs/b.png}",
            "\\marimo@u{absent}",
            "\\marimo@u{pending}",
            "\\marimo@c{blank}{}",
        ]
    )


def test_values_that_need_too_many_definitions_fail_before_tex_runs(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    readings: list[JsonValue] = [[] for _ in range(40_000)]
    notes: list[JsonValue] = [{"note": None} for _ in range(20_000)]

    _output, result = _render(project, {"readings": readings, "notes": notes})

    assert result.document is None
    (diagnostic,) = result.diagnostics
    assert diagnostic.code == "latex-values-too-large"
    assert diagnostic.message == (
        "The notebook values this document reads need more than 60,000 LaTeX "
        "definitions."
    )


@pytest.fixture
def stand_in(monkeypatch: pytest.MonkeyPatch) -> None:
    """Resolve the tectonic command without an installed Tectonic."""
    monkeypatch.setattr("shutil.which", lambda name: name)


def _tex_log(*lines: str) -> str:
    """Return log lines broken at 79 characters, as TeX writes them."""
    return "".join(
        "".join(f"{line[start : start + 79]}\n" for start in range(0, len(line), 79))
        for line in lines
    )


class _Tectonic:
    """Stand in for Tectonic, reporting a fixed result and logs."""

    def __init__(
        self,
        returncode: int,
        stderr: str,
        log: str = "",
        bibtex: str = "",
    ) -> None:
        self.result = ProviderCommandResult(returncode, "", stderr)
        self.log = log
        self.bibtex = bibtex

    def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        timeout: float = 120.0,
        environment: Mapping[str, str] | None = None,
    ) -> ProviderCommandResult:
        output = Path(command[command.index("--outdir") + 1])
        stem = Path(command[-1]).stem
        if self.result.returncode == 0:
            output.joinpath(f"{stem}.pdf").write_bytes(b"%PDF-1.5\n")
        output.joinpath(f"{stem}.log").write_text(self.log, encoding="utf-8")
        output.joinpath(f"{stem}.blg").write_text(self.bibtex, encoding="utf-8")
        return self.result


def test_errors_in_included_files_name_the_file_and_where_tex_stopped(
    tmp_path: Path,
    stand_in: None,
) -> None:
    project = _project(tmp_path)
    project.root.joinpath("sections").mkdir()
    project.root.joinpath("sections", "intro.tex").write_text("One.\n\\badmacro\n")
    stderr = (
        "note: Running TeX ...\n"
        "error: sections/intro:2: Undefined control sequence\n"
        "error: something bad happened inside XeTeX; its output follows:\n"
        "\n===\n(main.tex (sections/intro\n! Undefined control sequence.\n"
        "l.2 \\badmacro\n             \nNo pages of output.\n===\n"
        "error: the XeTeX engine had an unrecoverable error\n"
        "caused by: halted on potentially-recoverable error as specified\n"
    )

    _output, result = _render(project, {}, runner=_Tectonic(1, stderr))

    assert result.document is None
    (diagnostic,) = result.diagnostics
    assert diagnostic.code == "latex-compile-error"
    assert diagnostic.message == (
        'Undefined control sequence. TeX stopped after "\\badmacro".'
    )
    assert diagnostic.source == SourceLocation(
        PurePosixPath("sections/intro.tex"), 2, 1
    )


def test_errors_outside_the_project_keep_their_location_in_the_message(
    tmp_path: Path,
    stand_in: None,
) -> None:
    project = _project(tmp_path)
    stderr = (
        "error: hyperref.sty:4012: "
        "Package hyperref Error: Wrong DVI mode driver option.\n"
        "\nSee the hyperref package documentation for explanation.\n"
        "Type  H <return>  for immediate help\n"
        "error: the XeTeX engine had an unrecoverable error\n"
    )

    _output, result = _render(project, {}, runner=_Tectonic(1, stderr))

    (diagnostic,) = result.diagnostics
    assert diagnostic.source is None
    assert diagnostic.message == (
        "hyperref.sty:4012: Package hyperref Error: Wrong DVI mode driver option."
    )


def test_errors_that_outrun_the_kept_output_come_from_the_log(
    tmp_path: Path, stand_in: None
) -> None:
    project = _project(tmp_path)
    project.root.joinpath("sections").mkdir()
    project.root.joinpath("sections", "intro.tex").write_text(
        "One.\n" * 11 + "Then \\badmacro here.\n"
    )
    # Studio keeps the end of the transcript, after Tectonic's located line.
    stderr = "Overfull \\hbox in paragraph at lines 3--3\n" * 3
    log = _tex_log(
        "(./sections/intro.tex",
        "! Undefined control sequence.",
        "l.12 Then \\badmacro",
        "                     here.",
    )

    _output, result = _render(project, {}, runner=_Tectonic(1, stderr, log))

    (diagnostic,) = result.diagnostics
    assert diagnostic.message == (
        'Undefined control sequence. TeX stopped after "Then \\badmacro".'
    )
    assert diagnostic.source == SourceLocation(
        PurePosixPath("sections/intro.tex"), 12, 1
    )


def test_errors_in_files_that_source_does_not_show_name_them_in_the_message(
    tmp_path: Path, stand_in: None
) -> None:
    project = _project(tmp_path)
    project.root.joinpath("figure.pgf").write_text("\\badmacro\n")
    stderr = "error: figure.pgf:1: Undefined control sequence\n"

    _output, result = _render(project, {}, runner=_Tectonic(1, stderr))

    (diagnostic,) = result.diagnostics
    assert diagnostic.source is None
    assert diagnostic.message == "figure.pgf:1: Undefined control sequence."


def test_rendering_without_tectonic_names_the_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path)
    monkeypatch.setattr("shutil.which", lambda _name: None)

    with pytest.raises(ProviderError, match="cannot find the tectonic command"):
        _render(project, {})


class _Raising:
    """Stand in for a runner whose command ends with an error."""

    def __init__(self, error: ProviderCommandError) -> None:
        self.error = error

    def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        timeout: float = 120.0,
        environment: Mapping[str, str] | None = None,
    ) -> ProviderCommandResult:
        raise self.error


def _build(
    project: ViewProject,
    staging: Path,
    runner: ProviderRunner,
    *,
    cancelled: bool = False,
) -> BuildResult:
    request = provider_build_request(
        project, inspect_view_project_sync(project), staging
    )
    if cancelled:
        request.cancellation.cancel()
    return provider.build(replace(request, runner=runner))


def test_a_build_compiles_once_within_the_build_budget(
    tmp_path: Path, stand_in: None
) -> None:
    project = _project(tmp_path)
    compiles: list[float] = []

    class Recording(_Tectonic):
        def run(self, command, *, cwd, timeout=120.0, environment=None):
            compiles.append(timeout)
            return super().run(command, cwd=cwd, timeout=timeout)

    result = _build(project, tmp_path / "staging", Recording(0, ""))

    assert result.document == MAIN
    assert compiles == [120.0]


def test_a_build_reports_the_widest_size_the_document_places_each_figure_at(
    tmp_path: Path, stand_in: None
) -> None:
    project = _project(tmp_path)
    log = _tex_log(
        "marimo-size:250.38007::occupancy_heatmap:",
        "marimo-size:465.47974:120:teaser_figure:",
        "marimo-size:513::occupancy_heatmap:",
        'marimo-size:216::rows[0]["a long selector that TeX breaks across log lines"]:',
        "marimo-size:0::unsized:",
    )

    result = _build(project, tmp_path / "staging", _Tectonic(0, "", log))

    assert result.output_sizes == {
        "occupancy_heatmap": Size(513),
        "teaser_figure": Size(465.47974, 120),
        'rows[0]["a long selector that TeX breaks across log lines"]': Size(216),
    }


def test_sizes_after_a_log_line_broken_at_its_limit_are_read(
    tmp_path: Path, stand_in: None
) -> None:
    project = _project(tmp_path)
    log = "x" * 79 + "\nmarimo-size:250.38::occupancy_heatmap:\n"

    result = _build(project, tmp_path / "staging", _Tectonic(0, "", log))

    assert result.output_sizes == {"occupancy_heatmap": Size(250.38)}


def test_marimo_warnings_in_the_log_appear_beside_the_document(
    tmp_path: Path, stand_in: None
) -> None:
    project = _project(tmp_path)
    log = (
        "Package marimo Warning: scale resizes the output that Studio draws at its\n"
        "(marimo)                measured size, so its text loses its point size.\n"
        "(marimo)                Give width, or width and height, instead.\n"
    )

    _output, result = _render(project, {}, runner=_Tectonic(0, "", log))

    assert [item.message for item in result.diagnostics] == [
        "scale resizes the output that Studio draws at its measured size, so its "
        "text loses its point size. Give width, or width and height, instead."
    ]


def test_a_build_that_outlasts_its_budget_explains_the_first_compile(
    tmp_path: Path, stand_in: None
) -> None:
    project = _project(tmp_path)
    error = ProviderCommandError(
        "Provider commands exceeded their 120 second aggregate budget"
    )

    result = _build(project, tmp_path / "staging", _Raising(error))

    (diagnostic,) = result.diagnostics
    assert diagnostic.code == "latex-compile-unfinished"
    assert "Run `tectonic -X compile main.tex` in the view folder" in diagnostic.hint


@pytest.mark.parametrize(
    ("message", "cancelled"),
    (
        ("Provider command produced more output than Studio accepts", False),
        ("Provider commands exceeded their 120 second aggregate budget", True),
    ),
)
def test_other_build_command_errors_propagate(
    tmp_path: Path, stand_in: None, message: str, cancelled: bool
) -> None:
    project = _project(tmp_path)

    with pytest.raises(ProviderCommandError):
        _build(
            project,
            tmp_path / "staging",
            _Raising(ProviderCommandError(message)),
            cancelled=cancelled,
        )


def test_unlocated_failures_report_their_cause(tmp_path: Path, stand_in: None) -> None:
    project = _project(tmp_path)
    stderr = (
        "warning: sorry, PostScript images are not supported by Tectonic\n"
        "error: something bad happened inside xdvipdfmx; its output follows:\n"
        "error: the xdvipdfmx engine had an unrecoverable error\n"
        'caused by: pdf: image inclusion failed for "figs/clouds.eps" (page=1).\n'
    )

    _output, result = _render(project, {}, runner=_Tectonic(1, stderr))

    (diagnostic,) = result.diagnostics
    assert (
        diagnostic.message
        == 'pdf: image inclusion failed for "figs/clouds.eps" (page=1).'
    )
    assert diagnostic.source == SourceLocation(MAIN, 1, 1)


@pytest.mark.pixi
@tectonic
def test_a_document_without_pages_says_so(tmp_path: Path) -> None:
    project = _project(tmp_path, _document("% Nothing to typeset yet."))

    _output, result = _render(project, {})

    (diagnostic,) = result.diagnostics
    assert diagnostic.message == "main.tex typeset no pages."


def test_warnings_locate_undefined_references_and_bibliography_errors(
    tmp_path: Path,
    stand_in: None,
) -> None:
    project = _project(
        tmp_path,
        _document(
            "See \\cref{fig:occupancy-by-hour-and-weekday} and "
            "\\citep{candanedo2016accurate}.\n\\bibliography{refs}"
        ),
    )
    project.root.joinpath("refs.bib").write_text("@article{broken, title={A}\n")
    stderr = (
        "warning: main.tex:6: "
        "Underfull \\hbox (badness 10000) in paragraph at lines 6--6\n"
        "warning: main.tex:6: "
        "Overfull \\hbox (0.4pt too wide) in paragraph at lines 6--6\n"
        "warning: main.tex:5: "
        "Overfull \\hbox (17.66pt too wide) in alignment at lines 5--5\n"
        "warning: main.tex:5: \n"
        'Missing character: There is no \ufffd\ufffd\ufffd ("2013) in font ptmr8t!\n'
        'warning: could not represent character "\u2013" (0x2013) in font "ptmr8t"\n'
    )
    log = _tex_log(
        "LaTeX Warning: Reference `fig:occupancy-by-hour-and-weekday' on page 1 "
        "undefined on input line 5.",
        "Package natbib Warning: Citation `candanedo2016accurate' on page 1 "
        "undefined on input line 5.",
        "LaTeX Warning: Label `fig:a' multiply defined.",
        "LaTeX Warning: There were undefined references.",
    )
    bibtex = (
        "Database file #1: refs.bib\n"
        "Illegal end of database file---line 2 of file refs.bib\n"
        " : @article{broken, title={A}\n"
        "I'm skipping whatever remains of this entry\n"
        "I couldn't open database file other.bib\n"
        "---line 4 of file main.aux\n"
        'Warning--I didn\'t find a database entry for "candanedo2016accurate"\n'
    )

    _output, result = _render(project, {}, runner=_Tectonic(0, stderr, log, bibtex))

    assert result.document == PurePosixPath("main.pdf")
    assert [(item.message, item.source) for item in result.diagnostics] == [
        (
            "Overfull \\hbox (17.66pt too wide) in alignment at lines 5--5",
            SourceLocation(MAIN, 5, 1),
        ),
        (
            "Missing character: There is no \u2013 (U+2013) in font ptmr8t!",
            SourceLocation(MAIN, 5, 1),
        ),
        (
            "Reference `fig:occupancy-by-hour-and-weekday` is undefined.",
            SourceLocation(MAIN, 5, 11),
        ),
        (
            "Citation `candanedo2016accurate` is undefined.",
            SourceLocation(MAIN, 5, 57),
        ),
        ("Label `fig:a` is defined more than once.", None),
        (
            "BibTeX: Illegal end of database file",
            SourceLocation(PurePosixPath("refs.bib"), 2, 1),
        ),
        ("BibTeX: I couldn't open database file other.bib", None),
    ]
    assert {item.severity for item in result.diagnostics} == {"warning"}


@pytest.mark.pixi
@tectonic
def test_latex_starter_publishes_a_pdf(tmp_path: Path) -> None:
    project = _project(tmp_path)

    published = publish(project)

    assert set(published.files) == {
        PurePosixPath("index.html"),
        PurePosixPath("main.pdf"),
    }
    assert published.files[PurePosixPath("main.pdf")].startswith(b"%PDF-")


@pytest.mark.pixi
@tectonic
@pytest.mark.parametrize(("value", "succeeds"), ((7, True), (8, False)))
def test_render_binds_notebook_values(
    tmp_path: Path,
    value: int,
    succeeds: bool,
) -> None:
    project = _project(
        tmp_path,
        _document("\\expect{\\ifnum\\marimovalue[0]{n}=7 }{n is not seven}Ready"),
    )

    output, result = _render(project, {"n": value})

    assert (result.document is not None) is succeeds
    if succeeds:
        assert output.joinpath("main.pdf").read_bytes().startswith(b"%PDF-")
    else:
        (diagnostic,) = result.diagnostics
        assert diagnostic.message.startswith("Package expect Error: n is not seven.")
        assert diagnostic.source == SourceLocation(MAIN, 5, 1)


@pytest.mark.pixi
@tectonic
def test_notebook_text_longer_than_a_tex_line_still_renders(tmp_path: Path) -> None:
    project = _project(
        tmp_path, _document("\\sbox0{\\marimovalue{words}\\marimovalue{run}}Ready")
    )

    _output, result = _render(
        project, {"words": " ".join(["word"] * 60_000), "run": "x" * 250_000}
    )

    assert result.diagnostics == ()
    assert result.document == PurePosixPath("main.pdf")


@pytest.mark.pixi
@tectonic
def test_rows_repeat_for_each_item_with_its_selector_and_position(
    tmp_path: Path,
) -> None:
    project = _project(
        tmp_path,
        _document(
            "\\newcount\\rows\n"
            "\\begin{tabular}{lr}\n"
            "\\marimorows{report.sensors}{\\global\\advance\\rows 1 "
            "\\expect{\\IfMarimoTF{#1.label}{\\iftrue}{\\iffalse}}{no label}"
            '\\expect{\\IfMarimoTF{#1["odd key"]}{\\iftrue}{\\iffalse}}{no key}'
            "\\expect{\\IfMarimoTF{#1.zero}{\\iffalse}{\\iftrue}}{zero is true}"
            "\\expect{\\ifnum\\rows=#2 }{the position is not the row}"
            "\\marimovalue{#1.label} & \\marimovalue{#1.mean} \\\\}\n"
            "\\marimorows[1]{report.sensors}{\\global\\advance\\rows 10 \\\\}\n"
            "\\marimorows{report.none}{never \\\\}\n"
            "\\marimorows{report.empty}{never \\\\}\n"
            "\\end{tabular}\n"
            "\\expect{\\ifnum\\rows=12 }{expected two rows and one limited row}"
            "\\marimoforeach{report.sensors}{\\global\\advance\\rows 100 }"
            "\\expect{\\ifnum\\rows=212 }{expected two items}",
        ),
    )

    _output, result = _render(
        project,
        {
            "report.sensors": [
                {"label": "CO\u2082 & light", "mean": 583.5, "odd key": 1, "zero": 0},
                {"label": "50% humidity", "mean": 27.1, "odd key": 2, "zero": 0},
            ],
            "report.none": None,
            "report.empty": [],
        },
    )

    assert result.diagnostics == ()
    assert result.document == PurePosixPath("main.pdf")


@pytest.mark.pixi
@tectonic
def test_reads_typeset_their_values_in_the_document_s_formats(tmp_path: Path) -> None:
    project = _project(
        tmp_path,
        _document(
            "\\newcommand\\same[2]{\\sbox0{#1}\\sbox2{#2}"
            "\\expect{\\ifdim\\wd0=\\wd2 }{\\detokenize{#1} differs}}\n"
            "\\same{\\marimonum[share]{rate}}{\\qty{21.2}{\\percent}}"
            "\\same{\\marimonum{count}}{\\num{8143}}"
            "\\same{\\marimonum{peak}}{\\textemdash}"
            "\\same{\\marimonum{pending}}{\\textbf{??}}"
            "\\same{\\marimovalue[n/a]{peak}}{n/a}"
            "\\same{\\marimovalue{flag}}{true}"
            "\\same{\\marimodate[shortday]{day}}{Wed 4 Feb}"
            "\\same{\\marimotime{at}}{09:41}"
            "\\expect{\\IfMarimoTF{peak}{\\iffalse}{\\iftrue}}{null is true}"
            "\\expect{\\IfMarimoTF{pending}{\\iffalse}{\\iftrue}}{pending is true}"
            "\\section{\\marimovalue{title}}",
            preamble=(
                "\\usepackage[en-GB, calc]{datetime2}\n"
                "\\usepackage{siunitx}\n"
                "\\usepackage{hyperref}\n"
                "\\sisetup{mode=match, reset-text-family=false, "
                "reset-text-series=false, reset-text-shape=false, "
                "group-separator={,}}\n"
            ),
        ).replace(
            "\\begin{document}",
            "\\DeclareMarimoFormat{share}{scale=100, round-mode=places, "
            "round-precision=1, unit=\\percent}\n"
            "\\DTMsettimestyle{default}\\DTMsetup{showseconds=false}\n"
            "\\DTMnewdatestyle{shortday}{\\renewcommand*\\DTMdisplaydate[4]{"
            "\\DTMshortweekdayname{##4} \\number##3\\ \\DTMshortmonthname{##2}}"
            "\\renewcommand*\\DTMDisplaydate{\\DTMdisplaydate}}\n"
            "\\begin{document}",
        ),
    )

    _output, result = _render(
        project,
        {
            "rate": 0.2123,
            "count": 8143,
            "peak": None,
            "flag": True,
            "day": "2015-02-04",
            "at": "2015-02-04T09:41:00+01:00",
            "title": "\u03b1 \u2265 5",
        },
    )

    assert result.diagnostics == ()
    assert result.document == PurePosixPath("main.pdf")


@pytest.mark.pixi
@tectonic
def test_formats_loops_and_null_compose(tmp_path: Path) -> None:
    project = _project(
        tmp_path,
        _document(
            "\\newcommand\\same[2]{\\sbox0{#1}\\sbox2{#2}"
            "\\expect{\\ifdim\\wd0=\\wd2 }{\\detokenize{#1} differs}}\n"
            "\\DeclareMarimoFormat{share}{scale=100, round-mode=places, "
            "round-precision=1, unit=\\percent}\n"
            "\\same{\\marimonum[share, round-precision=3]{rate}}"
            "{\\qty{21.233}{\\percent}}"
            "\\same{$\\marimonum{peak}$}{\\textemdash}"
            "\\newcount\\items"
            "\\marimoforeach{rows}{\\global\\advance\\items 1 "
            "\\marimoforeach{#1.kids}{\\global\\advance\\items 10 }}"
            "\\expect{\\ifnum\\items=33 }{nested loops miscounted}Ready",
            preamble="\\usepackage{siunitx}\n",
        ),
    )

    _output, result = _render(
        project,
        {
            "rate": 0.21233,
            "peak": None,
            "rows": [{"kids": ["a", "b"]}, {"kids": []}, {"kids": ["c"]}],
        },
    )

    assert result.diagnostics == ()
    assert result.document == PurePosixPath("main.pdf")


@pytest.mark.pixi
@tectonic
@pytest.mark.parametrize(
    ("body", "preamble", "message"),
    (
        (
            "\\newcommand\\ifok[1]{\\IfMarimoTF{#1}{yes}{no}}\\ifok{flag}",
            "",
            "flag is not among the values Studio supplied.",
        ),
        (
            "\\section{Count \\marimonum{n}}Text\\newpage More",
            "\\usepackage{siunitx}\n\\pagestyle{headings}\n",
            "N is not among the values Studio supplied, and n is.",
        ),
    ),
)
def test_reads_studio_did_not_supply_name_their_cause(
    tmp_path: Path, body: str, preamble: str, message: str
) -> None:
    project = _project(tmp_path, _document(body, preamble=preamble))

    _output, result = _render(project, {"n": 7})

    assert result.document is None
    assert result.diagnostics[0].message.startswith(f"Package marimo Error: {message}")


@pytest.mark.pixi
@tectonic
def test_a_build_publishes_where_the_document_places_each_figure(
    tmp_path: Path,
) -> None:
    project = _project(
        tmp_path,
        _document(
            "\\marimographics[width=3in, totalheight=1in]{chart}\n"
            "\\marimographics[width=2in]{chart}\n"
            "\\begin{minipage}{4in}\\marimographics{table_figure}\\end{minipage}\n"
            "\\begin{minipage}{4in}\\marimographics[height=1in]{strip}\\end{minipage}\n"
            "\\marimographics[width=3in, height=1in, keepaspectratio]{fitted}"
        ),
    )

    with build_view_project_sync(project) as published:
        sizes = {
            site.targets: site.size
            for site in published.artifact.sites
            if site.kind == "output"
        }

    # TeX measures in scaled points, so the lengths land within a hair of bp.
    assert {
        target: (size.width, size.height) for target, size in sizes.items() if size
    } == {
        ("chart",): (pytest.approx(216), pytest.approx(72)),
        ("table_figure",): (pytest.approx(288), None),
        ("strip",): (pytest.approx(288), None),
        ("fitted",): (pytest.approx(216), None),
    }


@pytest.mark.pixi
@tectonic
@pytest.mark.parametrize("kind", ("output", "cell"))
@pytest.mark.parametrize("options", ("[width=8cm]", ""))
def test_images_are_placed_at_their_width_and_aspect_ratio(
    tmp_path: Path, kind: str, options: str
) -> None:
    image = pytest.importorskip("matplotlib.image")
    numpy = pytest.importorskip("numpy")
    command = "marimographics" if kind == "output" else "marimocell"
    png = io.BytesIO()
    image.imsave(png, numpy.zeros((300, 600, 3)), format="png")
    project = _project(
        tmp_path,
        _document(
            f"\\begin{{minipage}}{{8cm}}\\sbox0{{\\{command}{options}{{chart}}}}"
            "\\expect{\\ifdim\\wd0=8cm }{the image lost its width}"
            "\\expect{\\ifdim\\ht0>3.99cm }{the image is too short}"
            "\\expect{\\ifdim\\ht0<4.01cm }{the image is too tall}"
            "\\usebox0\\end{minipage}"
        ),
    )
    chart = Representation("image/png", png.getvalue())

    output, result = _render(
        project,
        {},
        outputs={"chart": chart} if kind == "output" else None,
        cells={"chart": chart} if kind == "cell" else None,
    )

    assert result.diagnostics == ()
    assert output.joinpath("main.pdf").read_bytes().startswith(b"%PDF-")


@pytest.mark.pixi
@tectonic
@pytest.mark.parametrize(
    ("options", "warning"),
    (
        ("height=1in", "height alone resizes the output"),
        ("scale=0.5", "scale resizes the output"),
        ("angle=90, width=1in", "angle turns the output"),
    ),
)
def test_options_that_resize_a_drawn_figure_warn(
    tmp_path: Path, options: str, warning: str
) -> None:
    project = _project(
        tmp_path, _document(f"\\noindent\\marimographics[{options}]{{chart}}")
    )

    _output, result = _render(project, {})

    (diagnostic,) = result.diagnostics
    assert diagnostic.message.startswith(warning)


@pytest.mark.pixi
@tectonic
@pytest.mark.parametrize(
    "body",
    (
        "\\marimographics[width=1in, angle=90]{chart}",
        "\\marimographics[width=2in, height=1in, keepaspectratio]{chart}",
        "\\marimocell[scale=0.5]{chart}",
    ),
)
def test_options_that_keep_a_drawn_figure_s_size_place_it_quietly(
    tmp_path: Path, body: str
) -> None:
    project = _project(tmp_path, _document(f"\\noindent{body}"))

    _output, result = _render(project, {})

    assert result.diagnostics == ()


@pytest.mark.pixi
@tectonic
def test_a_matplotlib_figure_is_placed_as_pdf(tmp_path: Path) -> None:
    figure_module = pytest.importorskip("matplotlib.figure")
    figure = figure_module.Figure(figsize=(4, 2))
    figure.subplots().plot([1, 3, 2])
    project = _project(
        tmp_path,
        _document(
            "\\sbox0{\\marimographics[width=8cm]{chart}}"
            "\\expect{\\ifdim\\wd0=8cm }{the figure lost its width}\\usebox0"
        ),
    )
    (read,) = inspect_view_project_sync(project).render_outputs

    chart = represent(figure, read.accept)
    output, result = _render(project, {}, outputs={"chart": chart})

    assert chart.media_type == "application/pdf"
    assert result.diagnostics == ()
    assert output.joinpath("main.pdf").read_bytes().startswith(b"%PDF-")


@pytest.mark.pixi
@tectonic
def test_a_frame_of_the_placed_size_stands_in_for_a_pending_figure(
    tmp_path: Path,
) -> None:
    project = _project(
        tmp_path,
        _document(
            "\\sbox0{\\marimographics[width=8cm, keepaspectratio]{chart}}"
            "\\expect{\\ifdim\\wd0=8cm }{the frame lost its width}"
            "\\expect{\\ifdim\\dimexpr\\ht0+\\dp0\\relax>4.4cm }"
            "{the frame is too short}"
            "\\expect{\\ifdim\\dimexpr\\ht0+\\dp0\\relax<4.6cm }"
            "{the frame is too tall}"
            "\\usebox0"
        ),
    )

    _output, result = _render(project, {})

    assert result.diagnostics == ()
    assert result.document == PurePosixPath("main.pdf")


@pytest.mark.pixi
@tectonic
@pytest.mark.parametrize(
    ("body", "message"),
    (
        (
            "\\marimovalue{report}",
            "report is a dictionary, and \\marimovalue reads text, numbers, and "
            "booleans.",
        ),
        (
            "\\begin{tabular}{l}\\marimorows{report}{#1 \\\\}\\end{tabular}",
            "report is a dictionary, and \\marimorows reads lists and tables.",
        ),
        (
            "\\marimonum{report.title}",
            "report.title is text, and \\marimonum reads numbers.",
        ),
        (
            "\\newcommand\\share[1]{\\marimonum{#1}}\\share{report.total}",
            "report.total is not among the values Studio supplied.",
        ),
    ),
)
def test_reads_of_the_wrong_kind_fail_at_the_command(
    tmp_path: Path, body: str, message: str
) -> None:
    project = _project(tmp_path, _document(body))

    _output, result = _render(project, {"report": {"title": "Q3"}})

    (diagnostic,) = result.diagnostics
    assert diagnostic.message.startswith(f"Package marimo Error: {message}")
    assert diagnostic.source == SourceLocation(MAIN, 5, 1)


@pytest.mark.pixi
@tectonic
def test_an_outdated_marimo_sty_names_its_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path, _document("Ready"))
    monkeypatch.setattr(_inputs, "INPUTS_VERSION", 3)

    _output, result = _render(project, {"n": 1})

    (diagnostic,) = result.diagnostics
    assert "Replace marimo.sty with the copy from the current LaTeX starter" in (
        diagnostic.message
    )


@pytest.mark.pixi
@tectonic
def test_documents_compile_without_shell_escape(tmp_path: Path) -> None:
    marker = tmp_path / "marker"
    project = _project(
        tmp_path, _document(f"\\immediate\\write18{{touch {marker.as_posix()}}}Ready")
    )

    _output, result = _render(project, {})

    assert result.document == PurePosixPath("main.pdf")
    assert not marker.exists()


@pytest.mark.pixi
@tectonic
def test_an_entry_in_a_folder_reads_values_beside_it(tmp_path: Path) -> None:
    project = _project(tmp_path)
    paper = project.root / "paper"
    paper.mkdir()
    project.root.joinpath("marimo.sty").rename(paper / "marimo.sty")
    project.root.joinpath(MAIN).rename(paper / "main.tex")
    (paper / "main.tex").write_text(
        _document("\\expect{\\ifnum\\marimovalue[0]{n}=7 }{n is not seven}Ready"),
        encoding="utf-8",
    )

    _output, result = _render(
        project, {"n": 7}, document=PurePosixPath("paper/main.tex")
    )

    assert result.diagnostics == ()
    assert result.document == PurePosixPath("main.pdf")


@pytest.mark.pixi
@tectonic
def test_escaped_text_has_every_glyph_in_t1_fonts(tmp_path: Path) -> None:
    project = _project(
        tmp_path,
        _document(
            "\\sbox0{\\marimovalue{text}}Ready", preamble="\\usepackage[T1]{fontenc}\n"
        ),
    )
    latin = "".join(map(chr, range(0xC0, 0x100)))

    _output, result = _render(project, {"text": f"{''.join(_SYMBOLS)} {latin}"})

    assert result.diagnostics == ()
    assert result.document == PurePosixPath("main.pdf")


@pytest.mark.pixi
@tectonic
def test_a_build_typesets_fallbacks_in_the_contents_and_at_row_starts(
    tmp_path: Path,
) -> None:
    project = _project(
        tmp_path,
        _document(
            "\\tableofcontents\n"
            "\\section{\\marimovalue{summary.title}}\n"
            "\\begin{tabular}{l}\\hline A \\\\ \\IfMarimoT{summary.total}{B \\\\}"
            "\\hline\\end{tabular}"
        ),
    )

    with build_view_project_sync(project):
        pass

    state = read_profile_state(project, "development")
    assert state is not None
    assert state.build.diagnostics == ()


@pytest.mark.pixi
@tectonic
def test_latex_errors_fail_the_build_at_their_source_line(tmp_path: Path) -> None:
    project = _project(tmp_path, _document("Fine.\n\\undefinedmacro"))

    with pytest.raises(ViewProjectError):
        build_view_project_sync(project)

    state = read_profile_state(project, "development")
    assert state is not None
    (diagnostic,) = state.build.diagnostics
    assert diagnostic.code == "latex-compile-error"
    assert diagnostic.message == (
        'Undefined control sequence. TeX stopped after "\\undefinedmacro".'
    )
    assert diagnostic.source == SourceLocation(MAIN, 6, 1)


@pytest.mark.pixi
@tectonic
def test_latex_builds_share_one_revision_across_profiles(tmp_path: Path) -> None:
    project = _project(tmp_path)

    with build_view_project_sync(project) as development:
        revision = development.artifact.artifact_revision
    with build_view_project_sync(project, profile="production") as production:
        assert production.artifact.artifact_revision == revision


@pytest.mark.pixi
@tectonic
def test_render_stops_at_its_deadline(tmp_path: Path) -> None:
    project = _project(tmp_path, _document("\\def\\forever{\\forever}\\forever"))

    with pytest.raises(ProviderCommandError, match="budget"):
        _render(project, {}, timeout=3.0)
