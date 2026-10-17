"""Check third-party provider packages through the public provider test kit."""

from __future__ import annotations

import asyncio
import importlib
import sys
from collections.abc import Callable, Iterator
from pathlib import Path, PurePosixPath
from textwrap import dedent
from typing import cast

import pytest

from marimo_studio.view_providers import ViewProvider
from marimo_studio.view_providers.testing import (
    CheckedView,
    ProviderCheckError,
    check_provider,
)

# A provider package that publishes page.md as HTML. Each test appends the
# behavior it checks.
PROVIDER = """
import html
from pathlib import PurePosixPath

from marimo_studio.view_providers import (
    BuildResult,
    BuildInput,
    ProjectInspection,
    ProviderAvailability,
    ProviderError,
    ProviderInfo,
    ProviderStarter,
    SourceDocument,
    SourceLocation,
    StarterPlan,
)

PAGE = PurePosixPath("page.md")


class PageProvider:
    info = ProviderInfo(
        title="Page",
        summary="One Markdown page.",
        options=frozenset({"heading"}),
    )
    starter = ProviderStarter("default", "Page", "One page.", (PAGE,))

    def availability(self):
        return ProviderAvailability(True)

    def starters(self):
        return (self.starter,)

    def create(self, starter, context):
        return StarterPlan(
            files={PAGE: b"First line\\nSecond line\\n"}, cell_targets=()
        )

    def inspect(self, request):
        return ProjectInspection(
            documents=(SourceDocument(PAGE, "markdown", "edit"),),
            inputs=(BuildInput(PAGE, "file"),),
        )

    def build(self, request):
        heading = html.escape(str(request.project.options.get("heading", "Page")))
        text = html.escape((request.project.root / PAGE).read_text())
        (request.staging_root / "index.html").write_text(
            f"<!doctype html><html><head><title>{heading}</title></head>"
            f'<body><main id="app-shell"><h1>{heading}</h1><p>{text}</p></main>'
            "</body></html>"
        )
        return BuildResult(PurePosixPath("index.html"))
"""

# Render page.md into an SVG card that draws the notebook's metric.
RENDERED = """
from marimo_studio.view_providers import (
    ProjectDiagnostic,
    Render,
    RenderFile,
    RenderResult,
    RenderValue,
    copy_inputs,
    render_page,
)


def inspect(self, request):
    return ProjectInspection(
        documents=(SourceDocument(PAGE, "markdown", "edit"),),
        inputs=(BuildInput(PAGE, "file"),),
        renders=(
            Render(PAGE, values=(RenderValue("metric", SourceLocation(PAGE, 1, 1)),)),
        ),
    )


def build(self, request):
    copy_inputs(request, request.template_root)
    return BuildResult(render_page(request, PAGE))


def render(self, request):
    metric = request.values.get("metric")
    if metric == "broken":
        problem = ProjectDiagnostic(
            "page-render-error",
            "error",
            "page.md cannot show this metric.",
            source=SourceLocation(PAGE, 1, 1),
        )
        return RenderResult(diagnostics=(problem,))
    card = PurePosixPath("card.svg")
    (request.output_root / card).write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg"><text>{metric!r}</text></svg>'
    )
    return RenderResult((RenderFile(card, "image/svg+xml"),), main=card)


PageProvider.inspect = inspect
PageProvider.build = build
PageProvider.render = render
"""


@pytest.fixture
def install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Callable[[str], ViewProvider]]:
    """Write ``page_views`` with the base provider plus ``extra`` and import it."""
    monkeypatch.syspath_prepend(str(tmp_path))

    def write(extra: str = "") -> ViewProvider:
        package = tmp_path / "page_views"
        package.mkdir(exist_ok=True)
        (package / "__init__.py").write_text(
            PROVIDER + dedent(extra) + "\n\nprovider = PageProvider()\n",
            encoding="utf-8",
        )
        return cast(ViewProvider, importlib.import_module("page_views").provider)

    yield write
    for name in [name for name in sys.modules if name.startswith("page_views")]:
        del sys.modules[name]


def test_provider_check_publishes_the_built_page(
    install: Callable[[str], ViewProvider],
) -> None:
    (view,) = check_provider(install(""), options={"heading": "Quarterly"})

    page = view.published[PurePosixPath("index.html")].decode()
    assert "<h1>Quarterly</h1>" in page


def test_undeclared_options_fail_the_check(
    install: Callable[[str], ViewProvider],
) -> None:
    with pytest.raises(ProviderCheckError, match=r"view\.toml sets 'port'"):
        check_provider(install(""), options={"port": 8080})


def test_inspection_errors_point_at_the_file_that_caused_them(
    install: Callable[[str], ViewProvider],
) -> None:
    provider = install(
        """
        def inspect(self, request):
            raise ProviderError(
                "page.md needs a title.",
                hint="Start page.md with a heading.\\n",
                source=SourceLocation(PAGE, 2, 1),
            )

        PageProvider.inspect = inspect
        """
    )

    with pytest.raises(
        ProviderCheckError,
        match=r"page\.md:2:1: page\.md needs a title\. Hint: Start page\.md",
    ):
        check_provider(provider)


def test_build_errors_keep_the_location_of_a_build_input(
    install: Callable[[str], ViewProvider],
) -> None:
    provider = install(
        """
        def build(self, request):
            raise ProviderError(
                "rows.csv has no header.",
                source=SourceLocation(PurePosixPath("rows.csv"), 1, 1),
            )

        PageProvider.build = build
        """
    )

    with pytest.raises(ProviderCheckError, match=r"rows\.csv:1:1: rows\.csv has no"):
        check_provider(provider)


@pytest.mark.parametrize(
    "statement",
    (
        "from marimo_studio._filesystem import paths",
        "from marimo_studio import _filesystem",
    ),
)
def test_private_studio_imports_fail_the_check(
    install: Callable[[str], ViewProvider],
    statement: str,
) -> None:
    provider = install(f"{statement}\n")

    with pytest.raises(ProviderCheckError, match=r"marimo_studio\._filesystem"):
        check_provider(provider)


def test_inspect_that_writes_to_the_project_fails_the_check(
    install: Callable[[str], ViewProvider],
) -> None:
    provider = install(
        """
        _inspect = PageProvider.inspect

        def inspect(self, request):
            (request.project.root / "generated.txt").write_text("cache")
            return _inspect(self, request)

        PageProvider.inspect = inspect
        """
    )

    with pytest.raises(ProviderCheckError, match=r"inspect\(\) changed the project"):
        check_provider(provider)


def test_render_receives_values_as_studio_supplies_them(
    install: Callable[[str], ViewProvider],
) -> None:
    (view,) = check_provider(install(RENDERED), values={"metric": 2.0})

    card = view.renders[PurePosixPath("page.md")]
    assert card.main == PurePosixPath("card.svg")
    assert b"<text>2</text>" in card.files[card.main]


def test_render_errors_fail_the_check_at_their_location(
    install: Callable[[str], ViewProvider],
) -> None:
    with pytest.raises(
        ProviderCheckError,
        match=r"page\.md:1:1: page\.md cannot show this metric\.",
    ):
        check_provider(install(RENDERED), values={"metric": "broken"})


@pytest.mark.parametrize(
    "statement",
    (
        "from marimo_studio.view_providers.testing import check_provider",
        "from marimo_studio.view_providers import *",
    ),
)
def test_provider_packages_may_import_the_public_modules(
    install: Callable[[str], ViewProvider],
    statement: str,
) -> None:
    provider = install(f"{statement}\n")

    assert check_provider(provider)


def test_namespace_package_providers_keep_the_sdk_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = tmp_path / "namespace_views"
    package.mkdir()
    (package / "page.py").write_text(
        PROVIDER
        + "from marimo_studio._filesystem import paths\n"
        + "\n\nprovider = PageProvider()\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    try:
        provider = importlib.import_module("namespace_views.page").provider
        with pytest.raises(ProviderCheckError, match=r"marimo_studio\._filesystem"):
            check_provider(provider)
    finally:
        for name in [
            name for name in sys.modules if name.startswith("namespace_views")
        ]:
            del sys.modules[name]


def test_provider_check_runs_inside_a_running_event_loop(
    install: Callable[[str], ViewProvider],
) -> None:
    provider = install("")

    async def check_from_async_code() -> tuple[CheckedView, ...]:
        return check_provider(provider)

    (view,) = asyncio.run(check_from_async_code())

    assert PurePosixPath("index.html") in view.published


# Render the card with regions: two Studio can show, one with reads the render
# does not read, one with a long label that holds a lone surrogate, and three
# Studio cannot.
LOCATED = """
from marimo_studio.view_providers import Rect, RenderRegion


def located(self, request):
    result = render(self, request)
    card = PurePosixPath("card.svg")
    at = SourceLocation(PAGE, 1, 1)
    return replace(
        result,
        regions=(
            RenderRegion(
                card,
                Rect(0.1, 0.2, 0.5, 0.25),
                reads=("metric", "missing", "\\udc00"),
                source=at,
                label="Metric",
            ),
            RenderRegion(
                card,
                Rect(0, 0, 1, 1.0004),
                reads=("report.rows[0]",),
                label="Row \\ud800" + "r" * 300,
            ),
            RenderRegion(card, Rect(0.5, 0.5, 0.6, 0.1), reads=("metric",)),
            RenderRegion(card, Rect(0, 0, 1, 1), reads=("missing",)),
            RenderRegion(card, Rect(0, 0, 1, 1), reads=("metric",), page=1),
        ),
    )


def inspect_report(self, request):
    inspection = inspect(self, request)
    (page,) = inspection.renders
    report = RenderValue("report", SourceLocation(PAGE, 2, 1))
    return replace(inspection, renders=(replace(page, values=(*page.values, report)),))


PageProvider.inspect = inspect_report
PageProvider.render = located
"""


def test_render_regions_keep_what_studio_can_show(
    install: Callable[[str], ViewProvider],
) -> None:
    (view,) = check_provider(
        install("from dataclasses import replace\n" + RENDERED + LOCATED),
        values={"metric": 2.0, "report": {"rows": [{"name": "north"}]}},
    )

    rendered = view.renders[PurePosixPath("page.md")]
    # A region without a source takes the source of the first read it shows.
    assert [region.to_dict() for region in rendered.regions] == [
        {
            "file": "card.svg",
            "rect": {"x": 0.1, "y": 0.2, "width": 0.5, "height": 0.25},
            "reads": ["metric"],
            "page": None,
            "start": None,
            "end": None,
            "source": {"path": "page.md", "line": 1, "column": 1},
            "label": "Metric",
        },
        {
            "file": "card.svg",
            "rect": {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0},
            "reads": ["report.rows[0]"],
            "page": None,
            "start": None,
            "end": None,
            "source": {"path": "page.md", "line": 2, "column": 1},
            "label": "Row " + "r" * 250 + "…",
        },
    ]
    (warning,) = rendered.warnings
    assert "left out 3 regions" in warning
    assert "inside the surface" in warning
    assert "left out 2 reads that the render does not read" in warning


# Render the card with one region per pixel of a 70 by 60 grid.
CROWDED = """
from marimo_studio.view_providers import Rect, RenderRegion


def crowded(self, request):
    result = render(self, request)
    card = PurePosixPath("card.svg")
    return replace(
        result,
        regions=tuple(
            RenderRegion(
                card, Rect(column / 70, row / 60, 1 / 70, 1 / 60), reads=("metric",)
            )
            for row in range(60)
            for column in range(70)
        ),
    )


PageProvider.render = crowded
"""


def test_a_render_with_more_regions_than_studio_keeps_still_publishes(
    install: Callable[[str], ViewProvider],
) -> None:
    (view,) = check_provider(
        install("from dataclasses import replace\n" + RENDERED + CROWDED),
        values={"metric": 2.0},
    )

    rendered = view.renders[PurePosixPath("page.md")]
    assert rendered.main == PurePosixPath("card.svg")
    assert len(rendered.regions) == 4_096
    (warning,) = rendered.warnings
    assert "kept the first 4,096 of 4,200 regions" in warning
