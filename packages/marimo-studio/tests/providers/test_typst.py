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
    encode_view_manifest,
    load_view_project,
)
from marimo_studio.errors import ViewProjectError
from marimo_studio.view_providers import (
    JsonValue,
    ProviderCancellation,
    ProviderCommandResult,
    RenderRequest,
    Representation,
    SourceLocation,
    ViewProject,
)
from marimo_studio.view_providers._builtin.typst import provider

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
) -> ViewProject:
    if notebook is not None:
        (tmp_path / "analysis.py").write_text(notebook, encoding="utf-8")
    plan = provider.create(
        provider.starters()[0],
        provider_starter_context(tmp_path, view_name="report"),
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
    return load_view_project(root)


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
            template_root=template,
            document=MAIN,
            values=values,
            outputs=outputs or {},
            cells=cells or {},
            output_root=output,
            cancellation=cancellation,
            runner=create_provider_runner(template, cancellation, timeout),
            command_timeout=timeout,
        )
    )


def test_typst_values_are_read_from_literal_value_calls(tmp_path: Path) -> None:
    project = _project(
        tmp_path,
        """#import "marimo.typ": marimo_value
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
    assert [(item.target, item.source) for item in inspection.render_values] == [
        ("title", SourceLocation(MAIN, 4, 11)),
        ('lookup["north"]', SourceLocation(MAIN, 6, 8)),
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
    (output,) = inspection.render_outputs
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
    assert [(item.target, item.source) for item in inspection.render_values] == [
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
    (cell,) = inspection.render_cells
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
    assert result.document is not None
    assert output.joinpath("document.pdf").read_bytes().startswith(b"%PDF-")


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
    (read,) = inspect_view_project_sync(project).render_outputs

    figure_pdf = represent(figure, read.accept)
    output, result = _render(project, {}, outputs={"chart": figure_pdf})

    assert figure_pdf.media_type == "application/pdf"
    assert result.diagnostics == ()
    assert output.joinpath("document.pdf").read_bytes().startswith(b"%PDF-")


def test_outputs_are_absent_until_studio_supplies_them(tmp_path: Path) -> None:
    project = _project(
        tmp_path,
        '#import "marimo.typ": marimo_output\n'
        '#assert(marimo_output("chart", default: "fallback") == "fallback")\n',
    )

    _output, result = _render(project, {})

    assert result.document is not None


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
def test_typst_starter_publishes_a_pdf_reading_report_when_defined(
    tmp_path: Path,
    notebook: str | None,
    targets: list[tuple[str, ...]],
) -> None:
    project = _project(tmp_path, notebook=notebook)

    published = publish(project)

    assert set(published.files) == {
        PurePosixPath("index.html"),
        PurePosixPath("main.pdf"),
    }
    assert published.files[PurePosixPath("main.pdf")].startswith(b"%PDF-")
    assert [site.targets for site in published.sites] == targets


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
    assert diagnostic.code == "typst-compile-error"
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
        Path(command[-1]).write_bytes(b"%PDF-1.7\n")
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
            template_root=project.root,
            document=MAIN,
            values={},
            outputs={},
            cells={},
            output_root=output,
            cancellation=ProviderCancellation(),
            runner=_PackageWarningCompiler(),
            command_timeout=30.0,
        )
    )

    assert result.document == PurePosixPath("document.pdf")
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

    assert (result.document is not None) is succeeds
    if succeeds:
        assert output.joinpath("document.pdf").read_bytes().startswith(b"%PDF-")
    else:
        (diagnostic,) = result.diagnostics
        assert diagnostic.message == "assertion failed: n is not seven"
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


def test_static_validation_checks_the_values_a_document_reads(
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
