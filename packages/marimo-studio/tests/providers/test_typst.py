from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath

import pytest
from marimo_export.values import represent

from marimo_studio._artifacts.repository import read_profile_state
from marimo_studio._processes.provider_runner import (
    ProviderCommandError,
    create_provider_runner,
)
from marimo_studio._validation.service import validate_studio
from marimo_studio._views.api import prepare_view
from marimo_studio._views.build import build_view_project_sync
from marimo_studio._views.inspection import inspect_view_project_sync
from marimo_studio._workspace import load_studio
from marimo_studio._workspace.project_manifest import (
    CatalogProject,
    encode_view_manifest,
)
from marimo_studio.errors import ViewProjectError
from marimo_studio.view_providers import (
    JsonValue,
    ProjectInspection,
    ProviderCancellation,
    ProviderCommandResult,
    Render,
    RenderFile,
    RenderRequest,
    Representation,
    Size,
    SourceLocation,
    ViewProject,
)
from marimo_studio.view_providers._builtin.typst import provider

from ..helpers import load_standalone_project
from ..provider_test_support import provider_starter_context, publish

pytestmark = pytest.mark.skipif(
    not provider.availability().available,
    reason="marimo-studio[typst] is unavailable",
)

MAIN = PurePosixPath("main.typ")


REPORT_NOTEBOOK = """import marimo

app = marimo.App()


@app.cell
def _():
    report = {"rooms": 12, "occupancy": 0.71}
    return (report,)
"""


def _project(
    tmp_path: Path,
    main: str | None = None,
    notebook: str | None = None,
) -> CatalogProject:
    if notebook is not None:
        (tmp_path / "analysis.py").write_text(notebook, encoding="utf-8")
    starter = provider.starters()[0]
    plan = provider.create(
        starter,
        provider_starter_context(tmp_path, view_name="report", starter=starter),
    )
    root = tmp_path / "report"
    for relative, content in plan.files.items():
        path = root.joinpath(*relative.parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    (root / "view.toml").write_text(
        encode_view_manifest("marimo-studio/typst"),
        encoding="utf-8",
    )
    if main is not None:
        (root / MAIN).write_text(main, encoding="utf-8")
    return load_standalone_project(root)


def _render(
    project: ViewProject,
    values: dict[str, JsonValue],
    timeout: float = 30.0,
    outputs: dict[str, Representation] | None = None,
    cells: dict[str, Representation] | None = None,
):
    template = project.root
    output = project.root.parent / f"output-{time.monotonic_ns()}"
    output.mkdir()
    cancellation = ProviderCancellation()
    return output, provider.render(
        RenderRequest(
            source=MAIN,
            template_root=template,
            values=values,
            outputs=outputs or {},
            cells=cells or {},
            output_root=output,
            cancellation=cancellation,
            runner=create_provider_runner(template, cancellation, timeout),
            command_timeout=timeout,
        )
    )


def _main_render(inspection: ProjectInspection) -> Render:
    """Return the one render a Typst view declares."""
    (render,) = inspection.renders
    assert render.source == MAIN
    return render


def test_typst_values_are_read_from_literal_value_calls(tmp_path: Path) -> None:
    project = _project(
        tmp_path,
        """#import "marimo.typ": marimo_value
#let opening = "/*"
// marimo_value("commented")
/* marimo_value("block") */
= Report #marimo_value("title", default: [Untitled])
`marimo_value("raw")`
Rows: #marimo_value("lookup[\\"north\\"]", default: ())
#let name = "dynamic"
#marimo_value(name, default: none)
Call value("prose") in running text.
""",
    )

    inspection = inspect_view_project_sync(project)

    assert inspection.diagnostics == ()
    assert inspection.sites == ()
    assert [(item.target, item.source) for item in _main_render(inspection).values] == [
        ("title", SourceLocation(MAIN, 5, 11)),
        ('lookup["north"]', SourceLocation(MAIN, 7, 8)),
    ]
    assert {item.path.as_posix() for item in inspection.documents} == {
        "AGENTS.md",
        "main.typ",
        "marimo.typ",
    }
    assert PurePosixPath("AGENTS.md") not in {item.path for item in inspection.inputs}


def test_typst_outputs_accept_pdf_then_vector_then_raster_images(
    tmp_path: Path,
) -> None:
    project = _project(
        tmp_path,
        """#import "marimo.typ": marimo_output, marimo_value
#figure(marimo_output("charts.sweep", width: 80%), caption: marimo_value("caption"))
// marimo_output("commented")
""",
    )

    inspection = inspect_view_project_sync(project)

    assert inspection.diagnostics == ()
    (output,) = _main_render(inspection).outputs
    assert (output.target, output.source) == (
        "charts.sweep",
        SourceLocation(MAIN, 2, 9),
    )
    assert output.accept == (
        "application/pdf",
        "image/svg+xml",
        "image/png",
        "image/jpeg",
        "image/webp",
        "image/gif",
    )
    assert [(item.target, item.source) for item in _main_render(inspection).values] == [
        ("caption", SourceLocation(MAIN, 2, 61)),
    ]


def test_typst_cells_are_read_by_name(tmp_path: Path) -> None:
    project = _project(
        tmp_path,
        '#import "marimo.typ": marimo_cell\n'
        '#figure(marimo_cell("revenue_plot", width: 80%))\n',
    )

    inspection = inspect_view_project_sync(project)

    assert inspection.diagnostics == ()
    (cell,) = _main_render(inspection).cells
    assert (cell.target, cell.source) == ("revenue_plot", SourceLocation(MAIN, 2, 9))
    assert cell.accept == (
        "application/pdf",
        "image/svg+xml",
        "image/png",
        "image/jpeg",
        "image/webp",
        "image/gif",
    )


SVG_CHART = (
    b'<svg xmlns="http://www.w3.org/2000/svg" width="600" height="300">'
    b'<rect width="600" height="300" fill="#b33a2e"/></svg>'
)


@pytest.mark.parametrize("kind", ("output", "cell"))
def test_render_places_images_at_their_size(tmp_path: Path, kind: str) -> None:
    project = _project(
        tmp_path,
        f'#import "marimo.typ": marimo_{kind}\n'
        f'#let chart = marimo_{kind}("chart", width: 8cm)\n'
        '#assert(chart != none, message: "the figure is missing")\n'
        "#context {\n"
        "  let size = measure(chart)\n"
        '  assert(size.width == 8cm, message: "the figure lost its width")\n'
        '  assert(size.height == 4cm, message: "the figure lost its aspect ratio")\n'
        "}\n"
        "#chart\n",
    )

    media = {"chart": Representation("image/svg+xml", SVG_CHART)}
    output, result = _render(
        project,
        {},
        outputs=media if kind == "output" else None,
        cells=media if kind == "cell" else None,
    )

    assert result.diagnostics == ()
    assert result.main == PurePosixPath("main.pdf")
    assert output.joinpath("main.pdf").read_bytes().startswith(b"%PDF-")


def test_render_places_a_matplotlib_figure_as_pdf(tmp_path: Path) -> None:
    figure_module = pytest.importorskip("matplotlib.figure")
    figure = figure_module.Figure(figsize=(4, 2))
    figure.subplots().plot([1, 3, 2])
    project = _project(
        tmp_path,
        '#import "marimo.typ": marimo_output\n'
        '#let chart = marimo_output("chart", width: 8cm)\n'
        '#assert(chart != none, message: "the figure is missing")\n'
        "#chart\n",
    )
    (read,) = _main_render(inspect_view_project_sync(project)).outputs

    figure_pdf = represent(figure, read.accept)
    output, result = _render(project, {}, outputs={"chart": figure_pdf})

    assert figure_pdf.media_type == "application/pdf"
    assert result.diagnostics == ()
    assert output.joinpath("main.pdf").read_bytes().startswith(b"%PDF-")


def test_render_locates_outputs_cells_and_regions_on_their_pages(
    tmp_path: Path,
) -> None:
    project = _project(
        tmp_path,
        '#import "marimo.typ": marimo_cell, marimo_output, marimo_region, '
        "marimo_value\n"
        "#set page(width: 20cm, height: 10cm, margin: 1cm)\n"
        '#figure(marimo_output("chart", width: 8cm), caption: [Chart])\n'
        "#pagebreak()\n"
        '#marimo_region("report.rooms", label: "Rooms")[\n'
        '  Rooms: #marimo_value("report.rooms")\n'
        "]\n"
        '#let summary = "summary"\n'
        "#marimo_cell(summary, width: 4cm)\n",
    )
    media = Representation("image/svg+xml", SVG_CHART)

    _output, result = _render(
        project,
        {"report.rooms": 12},
        outputs={"chart": media},
        cells={"summary": media},
    )

    assert result.diagnostics == ()
    regions = {region.reads[0]: region for region in result.regions}
    chart, rooms = regions["chart"], regions["report.rooms"]
    summary = regions["summary"]
    assert (chart.file, chart.page, chart.label) == (PurePosixPath("main.pdf"), 1, None)
    # 8cm wide and 4cm tall, centered on a 20cm by 10cm page below a 1cm margin.
    assert chart.rect.width == pytest.approx(0.4)
    assert chart.rect.height == pytest.approx(0.4)
    assert chart.rect.x == pytest.approx(0.3)
    assert chart.rect.y == pytest.approx(0.1)
    assert (rooms.page, rooms.label) == (2, "Rooms")
    assert rooms.rect.x == pytest.approx(0.05)
    assert summary.page == 2
    assert summary.rect.width == pytest.approx(0.2)


def test_render_locates_outputs_on_pages_that_grow_with_their_content(
    tmp_path: Path,
) -> None:
    project = _project(
        tmp_path,
        '#import "marimo.typ": marimo_output\n'
        "#set page(width: 12cm, height: auto, margin: 1cm)\n"
        '#marimo_output("chart", width: 10cm)\n',
    )
    media = Representation("image/svg+xml", SVG_CHART)

    _output, result = _render(project, {}, outputs={"chart": media})

    (chart,) = result.regions
    # The 10cm by 5cm chart fills the page between its 1cm margins.
    assert chart.page == 1
    assert chart.rect.x == pytest.approx(1 / 12)
    assert chart.rect.width == pytest.approx(10 / 12)
    assert chart.rect.y == pytest.approx(1 / 7)
    assert chart.rect.height == pytest.approx(5 / 7)


def test_render_locates_an_output_wider_than_its_container(tmp_path: Path) -> None:
    project = _project(
        tmp_path,
        '#import "marimo.typ": marimo_output\n'
        "#set page(width: 12cm, height: 8cm, margin: 2cm)\n"
        '#marimo_output("chart", width: 10cm)\n',
    )
    media = Representation("image/svg+xml", SVG_CHART)

    _output, result = _render(project, {}, outputs={"chart": media})

    (chart,) = result.regions
    # The chart keeps its 10cm width past the 8cm between the margins.
    assert chart.rect.x == pytest.approx(2 / 12)
    assert chart.rect.width == pytest.approx(10 / 12)


def test_regions_keep_inline_text_in_its_paragraph(tmp_path: Path) -> None:
    project = _project(
        tmp_path,
        '#import "marimo.typ": marimo_region, marimo_value\n'
        "#set page(width: 12cm, height: 8cm, margin: 1cm)\n"
        'Rooms #marimo_region("report.rooms")[#marimo_value("report.rooms")] '
        'at #marimo_region("report.occupancy")[#marimo_value("report.occupancy")].\n',
    )

    _output, result = _render(project, {"report.rooms": 12, "report.occupancy": 0.71})

    rooms, occupancy = sorted(result.regions, key=lambda region: region.rect.x)
    assert rooms.rect.y == pytest.approx(occupancy.rect.y)
    assert rooms.rect.x + rooms.rect.width < occupancy.rect.x
    assert rooms.rect.height < 0.1


def test_outputs_and_none_values_place_their_default(tmp_path: Path) -> None:
    project = _project(
        tmp_path,
        '#import "marimo.typ": marimo_output, marimo_value\n'
        '#marimo_output("chart", default: [#metadata("fallback") <shown>])\n'
        "#context assert(query(<shown>).len() == 1)\n"
        '#assert(marimo_value("peak.label", default: "n/a") == "n/a")\n',
    )

    _output, result = _render(project, {"peak.label": None})

    assert result.diagnostics == ()
    assert result.main == PurePosixPath("main.pdf")


def test_a_build_records_where_the_document_places_each_figure(
    tmp_path: Path,
) -> None:
    project = _project(
        tmp_path,
        '#import "marimo.typ": marimo_output\n'
        "#set page(width: 300pt, height: auto, margin: 50pt)\n"
        '#marimo_output("chart", width: 40pt)\n'
        '#marimo_output("chart", width: 50% + 10pt, height: 1in)\n'
        '#block(width: 120pt, marimo_output("wide"))\n'
        '#marimo_output("tall", height: 2in)\n',
    )

    with build_view_project_sync(project) as published:
        sizes = {
            site.targets: site.size
            for site in published.artifact.sites
            if site.kind == "output" and site.render == MAIN
        }

    assert sizes == {
        ("chart",): Size(110, 72),
        ("wide",): Size(120),
        ("tall",): Size(height=144),
    }


def test_invalid_value_selectors_are_reported_at_their_call(tmp_path: Path) -> None:
    project = _project(
        tmp_path, '#import "marimo.typ": marimo_value\n#marimo_value("rows..")\n'
    )

    (diagnostic,) = inspect_view_project_sync(project).diagnostics

    assert diagnostic.code == "render-value-invalid"
    assert diagnostic.source == SourceLocation(MAIN, 2, 2)


@pytest.mark.parametrize(
    ("notebook", "targets"),
    ((REPORT_NOTEBOOK, [("report",)]), (None, [])),
)
def test_typst_starter_publishes_a_page_showing_the_render_of_its_entry(
    tmp_path: Path,
    notebook: str | None,
    targets: list[tuple[str, ...]],
) -> None:
    project = _project(tmp_path, notebook=notebook)

    published = publish(project)

    assert set(published.files) == {PurePosixPath("index.html")}
    page = published.files[PurePosixPath("index.html")].decode()
    assert '<marimo-output render="main.typ"></marimo-output>' in page
    assert [site.targets for site in published.sites] == targets
    assert {site.render for site in published.sites} <= {MAIN}


def test_typst_build_keeps_the_sources_as_the_private_render_template(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path, notebook=REPORT_NOTEBOOK)

    with build_view_project_sync(project) as lease:
        template = lease.artifact.template
        public = {item.path for item in lease.artifact.files}
        copy = tmp_path / "template-copy"
        lease.copy_template(copy)

    assert template is not None
    assert template.renders == (MAIN,)
    assert MAIN in {item.path for item in template.files}
    assert MAIN not in public
    assert copy.joinpath(MAIN).read_text(encoding="utf-8") == (
        project.root.joinpath(MAIN).read_text(encoding="utf-8")
    )


def test_typst_builds_share_one_revision_across_profiles(tmp_path: Path) -> None:
    project = _project(tmp_path, notebook=REPORT_NOTEBOOK)

    with build_view_project_sync(project) as development:
        revision = development.artifact.artifact_revision
    with build_view_project_sync(project, profile="production") as production:
        assert production.artifact.artifact_revision == revision


def test_typst_errors_fail_the_build_at_their_source_line(tmp_path: Path) -> None:
    project = _project(
        tmp_path,
        '#import "marimo.typ": marimo_value\n\n'
        '#let rows = marimo_value("rows")\n#rows.len()\n',
    )

    with pytest.raises(ViewProjectError):
        build_view_project_sync(project)

    state = read_profile_state(project, "development")
    assert state is not None
    (diagnostic,) = state.build.diagnostics
    assert diagnostic.code == "typst-compile-error", diagnostic
    assert diagnostic.source is not None
    assert (diagnostic.source.path, diagnostic.source.line) == (MAIN, 4)


class _PackageWarningCompiler:
    """Stand in for the compile script and report a warning from a package."""

    def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        timeout: float = 120.0,
        environment: Mapping[str, str] | None = None,
    ) -> ProviderCommandResult:
        # python -I _compile.py ROOT ENTRY INPUTS OUTPUT [--regions]
        Path(command[6]).write_bytes(b"%PDF-1.7\n")
        warning = {
            "message": "`cetz.draw.content` is deprecated",
            "hints": [],
            "path": "@preview/cetz:0.3.4/src/draw.typ",
            "line": 12,
            "column": 3,
        }
        return ProviderCommandResult(0, json.dumps({"warnings": [warning]}), "")


def test_render_keeps_package_locations_in_the_message(tmp_path: Path) -> None:
    project = _project(tmp_path)
    output = tmp_path / "output"
    output.mkdir()

    result = provider.render(
        RenderRequest(
            source=MAIN,
            template_root=project.root,
            values={},
            outputs={},
            cells={},
            output_root=output,
            cancellation=ProviderCancellation(),
            runner=_PackageWarningCompiler(),
            command_timeout=30.0,
        )
    )

    assert result.main == PurePosixPath("main.pdf")
    (warning,) = result.diagnostics
    assert warning.source is None
    assert warning.message == (
        "@preview/cetz:0.3.4/src/draw.typ:12:3: `cetz.draw.content` is deprecated"
    )


@pytest.mark.parametrize(("value", "succeeds"), ((7, True), (8, False)))
def test_render_binds_notebook_values(
    tmp_path: Path,
    value: int,
    succeeds: bool,
) -> None:
    project = _project(
        tmp_path,
        '#import "marimo.typ": marimo_value\n'
        '#assert(marimo_value("n", default: 0) == 7, message: "n is not seven")\n'
        "Ready\n",
    )

    output, result = _render(project, {"n": value})

    assert (result.main is not None) is succeeds
    if succeeds:
        assert result.files == (
            RenderFile(PurePosixPath("main.pdf"), "application/pdf"),
        )
        assert output.joinpath("main.pdf").read_bytes().startswith(b"%PDF-")
    else:
        (diagnostic,) = result.diagnostics
        assert "n is not seven" in diagnostic.message
        assert diagnostic.source is not None
        assert (diagnostic.source.path, diagnostic.source.line) == (MAIN, 2)


def test_render_stops_at_its_deadline(tmp_path: Path) -> None:
    project = _project(
        tmp_path,
        '#import "marimo.typ": marimo_value\n'
        "#let total = 0\n"
        '#for i in range(marimo_value("n", default: 1)) { total += 1 }\n'
        "#total\n",
    )

    with pytest.raises(ProviderCommandError, match="budget"):
        _render(project, {"n": 1_000_000_000}, timeout=1.0)


def test_static_validation_checks_the_values_a_render_reads(
    notebook_path: Path,
) -> None:
    setup = prepare_view(notebook_path, "report", starter="marimo-studio/typst:default")
    setup.root.joinpath(MAIN).write_text(
        '#import "marimo.typ": marimo_value\n'
        '#marimo_value("doubled", default: 0) '
        '#marimo_value("missing_total", default: 0)\n',
        encoding="utf-8",
    )

    async def unused_runtime(*_args: object, **_kwargs: object) -> tuple[()]:
        return ()

    run = asyncio.run(
        validate_studio(
            load_studio(notebook_path),
            level="static",
            runtime_checker=unused_runtime,
        )
    )

    assert {issue.target for issue in run.report.issues if issue.view == "report"} == {
        "missing_total"
    }


def test_computed_output_targets_render_their_default(tmp_path: Path) -> None:
    project = _project(
        tmp_path,
        '#import "marimo.typ": marimo_output\n'
        "#let chart(name) = figure(marimo_output(name, width: 80%))\n"
        '#chart("plot")\n',
    )
    assert _main_render(inspect_view_project_sync(project)).outputs == ()

    with build_view_project_sync(project, profile="production"):
        pass
    output, result = _render(project, {})

    assert result.diagnostics == ()
    assert output.joinpath("main.pdf").read_bytes().startswith(b"%PDF-")


def test_build_retains_errors_from_data_inputs(tmp_path: Path) -> None:
    project = _project(tmp_path, '#let d = xml("data.xml")\nHello\n')
    project.root.joinpath("data.xml").write_text(
        "<root>\n<item>\n</root>\n", encoding="utf-8"
    )

    with pytest.raises(ViewProjectError):
        build_view_project_sync(project, profile="production")

    state = read_profile_state(project, "production")
    assert state is not None
    (diagnostic,) = state.build.diagnostics
    assert diagnostic.code == "typst-compile-error", diagnostic
    assert "data.xml" in diagnostic.message
    assert "XML" in diagnostic.message
    assert diagnostic.source is None


@pytest.mark.parametrize(
    "main,targets",
    [
        ('Text: marimo_value("missing")\n', []),
        ('#marimo_value("real") marimo_value("missing")\n', ["real"]),
        (
            '#let f(name) = marimo_value("real")\nPlain marimo_value("missing")',
            ["real"],
        ),
        (
            '#{ let x = marimo_value("first");\n marimo_value("second") }',
            ["first", "second"],
        ),
        ('#let f = [marimo_value("missing") #marimo_value("real")]\n', ["real"]),
        ('#(marimo_value("real"))\n', ["real"]),
        ('#box(width: 1em)marimo_value("missing")\n', []),
        ('#strong[Total]marimo_value("missing")\n', []),
        ('#"label"marimo_value("missing")\n', []),
        ('#{ 1 }marimo_value("missing")\n', []),
        ('#marimo_value("real").at(0)marimo_value("missing")\n', ["real"]),
        (
            '#figure(marimo_value("first"))[#marimo_value("second")]\n',
            ["first", "second"],
        ),
    ],
)
def test_inspection_reads_typst_code_expressions(
    tmp_path: Path, main: str, targets: list[str]
) -> None:
    inspection = inspect_view_project_sync(_project(tmp_path, main))
    assert [read.target for read in _main_render(inspection).values] == targets


def test_inspection_handles_oversized_unicode_escape(tmp_path: Path) -> None:
    inspection = inspect_view_project_sync(
        _project(tmp_path, r'#marimo_value("\u{FFFFFFFFFFFFFFFFFFFFFF}", default: 1)')
    )

    assert _main_render(inspection).values == ()
    assert MAIN in {document.path for document in inspection.documents}
