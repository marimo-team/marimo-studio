from __future__ import annotations

import shutil
from dataclasses import replace
from pathlib import Path, PurePosixPath

import pytest

from marimo_studio._artifacts.repository import read_profile_state
from marimo_studio._views.build import build_view_project_sync
from marimo_studio._views.inspection import inspect_view_project_sync
from marimo_studio._workspace.project_manifest import encode_view_manifest
from marimo_studio.errors import ConfigurationError, ViewProjectError
from marimo_studio.view_providers import (
    BuildInput,
    BuildRequest,
    BuildResult,
    InspectionRequest,
    ProjectDiagnostic,
    ProjectInspection,
    ProjectionSite,
    ProviderAvailability,
    ProviderInfo,
    RenderValue,
    SourceDocument,
    SourceLocation,
    ViewProject,
    html_sites,
)
from marimo_studio.view_providers._artifact_sites import (
    artifact_sites,
    inspection_sites,
)
from marimo_studio.view_providers._host.registry import ProviderRegistry
from marimo_studio.view_providers._validation import accept_diagnostics

from ..provider_test_support import (
    ProviderStub,
    candidate,
    install_registry,
    publish,
)

ENTRY = PurePosixPath("index.html")


class CopyProvider(ProviderStub):
    """Report hosts with html_sites() and publish the snapshot entry as built."""

    info = ProviderInfo("Copy", "Copies one page.")

    def __init__(self) -> None:
        super().__init__("test-copy/page", "default")
        self.sites: tuple[ProjectionSite, ...] | None = None
        self.documents: tuple[SourceDocument, ...] = ()
        self.build_diagnostic: str | None = None
        self.drop_hosts = False

    def availability(self) -> ProviderAvailability:
        return ProviderAvailability(True)

    def inspect(self, request: InspectionRequest) -> ProjectInspection:
        source = request.project.root.joinpath(ENTRY).read_bytes()
        sites, diagnostics = html_sites(ENTRY, source)
        return ProjectInspection(
            documents=(SourceDocument(ENTRY, "html", "edit"), *self.documents),
            inputs=(
                BuildInput(ENTRY, "file"),
                BuildInput(PurePosixPath("view.toml"), "file"),
            ),
            sites=sites if self.sites is None else self.sites,
            diagnostics=diagnostics,
        )

    def build(self, request: BuildRequest) -> BuildResult:
        built = request.project.root.joinpath(ENTRY)
        if self.drop_hosts:
            request.staging_root.joinpath(ENTRY).write_text(
                '<!doctype html><html><head></head><body><main id="app-shell">'
                "</main></body></html>",
                encoding="utf-8",
            )
            return BuildResult(ENTRY, ())
        shutil.copy2(built, request.staging_root.joinpath(ENTRY))
        if self.build_diagnostic is None:
            return BuildResult(ENTRY, ())
        lines = built.read_text(encoding="utf-8").splitlines()
        line = next(
            index
            for index, text in enumerate(lines, 1)
            if self.build_diagnostic in text
        )
        column = lines[line - 1].index(self.build_diagnostic) + 1
        return BuildResult(
            ENTRY,
            (
                ProjectDiagnostic(
                    code="copy-check-warning",
                    severity="warning",
                    message=f"Found {self.build_diagnostic}.",
                    source=SourceLocation(ENTRY, line, column),
                ),
            ),
        )


def _project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    page: bytes,
) -> tuple[ViewProject, CopyProvider]:
    provider = CopyProvider()
    registry = ProviderRegistry(
        (candidate("page", provider, distribution="test-copy"),)
    )
    install_registry(monkeypatch, registry)
    root = tmp_path / "view"
    root.mkdir()
    key = registry.ids[0]
    root.joinpath("view.toml").write_text(encode_view_manifest(key), encoding="utf-8")
    root.joinpath(ENTRY).write_bytes(page)
    return ViewProject("dashboard", root, root / "view.toml", key, {}), provider


def _page(body: str) -> bytes:
    return (
        '<!doctype html>\r\n<html><head><meta charset="utf-8"></head><body>\r\n'
        f'<main id="app-shell">\r\n{body}\r\n</main>\r\n</body></html>\r\n'
    ).encode()


def test_published_hosts_carry_site_ids_at_their_exact_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = _page(
        "<script>const fake = '<marimo-cell name=\"script\">';</script>\r\n"
        "<style>.fake::after { content: '<span mo-value=\"style\">'; }</style>\r\n"
        '<!-- <marimo-output value="comment"></marimo-output> -->\r\n'
        '<p title="1 > 0">Résumé 📈 '
        '<strong data-label=">" mo-value="total"></strong></p>\r\n'
        '<marimo-cell name="summary"></marimo-cell>'
    )
    project, _provider = _project(tmp_path, monkeypatch, page)

    published = publish(project)

    built = published.files[ENTRY].decode("utf-8")
    value, cell = published.sites
    assert built == page.decode("utf-8").replace(
        'mo-value="total"', f'mo-value="total" data-marimo-studio-site="{value.id}"'
    ).replace('name="summary"', f'name="summary" data-marimo-studio-site="{cell.id}"')
    assert project.root.joinpath(ENTRY).read_bytes() == page


def test_build_diagnostics_point_at_authored_columns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = _page('<marimo-cell name="a"></marimo-cell><b mo-value="x"></b> CHECK-ME')
    project, provider = _project(tmp_path, monkeypatch, page)
    provider.build_diagnostic = "CHECK-ME"

    published = publish(project)

    (diagnostic,) = published.diagnostics
    lines = page.decode("utf-8").splitlines()
    line = next(index for index, text in enumerate(lines, 1) if "CHECK-ME" in text)
    assert diagnostic.source == SourceLocation(
        ENTRY,
        line,
        lines[line - 1].index("CHECK-ME") + 1,
    )


@pytest.mark.parametrize(
    ("offset", "message"),
    (
        ("counted-in-characters", "outside its host start tag"),
        ("before-the-host", "precedes its host"),
    ),
)
def test_invalid_site_offsets_fail_the_build_at_the_host(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    offset: str,
    message: str,
) -> None:
    page = _page('<p>📈</p><marimo-cell name="summary"></marimo-cell>')
    project, provider = _project(tmp_path, monkeypatch, page)
    (site,), _ = html_sites(ENTRY, page)
    offsets = {
        "counted-in-characters": site.offset - len("📈".encode()) + 1,
        "before-the-host": page.index(b"<main") + len(b"<main"),
    }
    provider.sites = (replace(site, offset=offsets[offset]),)

    with pytest.raises(ViewProjectError, match=message):
        build_view_project_sync(project)

    state = read_profile_state(project, "development")
    assert state is not None
    (diagnostic,) = state.build.diagnostics
    assert diagnostic.code == "projection-site-invalid"
    assert diagnostic.source == site.source


def test_sites_accept_columns_counted_in_utf16(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = _page(f'<p>{"📈" * 40}</p><marimo-cell name="summary"></marimo-cell>')
    project, provider = _project(tmp_path, monkeypatch, page)
    (site,), _ = html_sites(ENTRY, page)
    utf16 = replace(site.source, column=site.source.column + 40)
    provider.sites = (replace(site, source=utf16),)

    published = publish(project)

    assert published.sites[0].source == utf16


def test_hosts_missing_from_the_build_output_are_reported(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, provider = _project(
        tmp_path,
        monkeypatch,
        _page('<marimo-cell name="summary"></marimo-cell>'),
    )
    provider.drop_hosts = True

    published = publish(project)

    (diagnostic,) = published.diagnostics
    assert (diagnostic.code, diagnostic.severity) == (
        "projection-site-missing",
        "warning",
    )
    assert diagnostic.source == published.sites[0].source


def test_site_ids_survive_layout_edits_and_number_repeated_targets() -> None:
    first = _page(
        '<marimo-output value="summary"></marimo-output>'
        '<marimo-output value="chart"></marimo-output>'
        '<marimo-output value="chart"></marimo-output>'
    )
    edited = _page(
        "<h2>Charts</h2>\r\n"
        '<section><marimo-output value="chart"></marimo-output></section>'
        '<marimo-output value="chart"></marimo-output>'
    )

    before = artifact_sites(html_sites(ENTRY, first)[0])
    after = artifact_sites(html_sites(ENTRY, edited)[0])

    assert [site.id for site in before[1:]] == [site.id for site in after]
    assert len({site.id for site in before}) == 3


def test_projection_hosts_and_render_reads_of_one_target_get_distinct_ids() -> None:
    (site,), _ = html_sites(ENTRY, _page('<span mo-value="summary"></span>'))
    inspection = ProjectInspection(
        documents=(SourceDocument(ENTRY, "html", "edit"),),
        inputs=(BuildInput(ENTRY, "file"),),
        sites=(site,),
        render_values=(RenderValue("summary", SourceLocation(ENTRY, 1, 1)),),
    )

    ids = [item.id for item in inspection_sites(inspection)]

    assert len(ids) == len(set(ids)) == 2


@pytest.mark.parametrize("problem", ("outside-inputs", "duplicate-offset"))
def test_provider_sites_must_be_unique_build_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    problem: str,
) -> None:
    project, provider = _project(
        tmp_path,
        monkeypatch,
        _page('<marimo-cell name="summary"></marimo-cell>'),
    )
    (site,), _ = html_sites(ENTRY, project.root.joinpath(ENTRY).read_bytes())
    if problem == "duplicate-offset":
        provider.sites = (site, replace(site, targets=("other",)))
        expected = "unique projection site offsets"
    else:
        notes = PurePosixPath("notes.html")
        project.root.joinpath(notes).write_text("<p></p>", encoding="utf-8")
        provider.documents = (SourceDocument(notes, "html", "edit"),)
        provider.sites = (replace(site, source=replace(site.source, path=notes)),)
        expected = "outside its build inputs"

    with pytest.raises(ConfigurationError, match=expected):
        publish(project)


def test_output_hosts_publish_the_media_types_they_accept(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = _page(
        '<marimo-output value="chart" accept="Image/SVG+xml, image/png">'
        "</marimo-output>"
    )
    project, _provider = _project(tmp_path, monkeypatch, page)

    published = publish(project)

    (site,) = published.sites
    assert site.accept == ("image/svg+xml", "image/png")


@pytest.mark.parametrize(
    ("accept", "problem"),
    [
        (
            "png",
            "a page shows image/svg+xml, image/png, image/jpeg, image/gif, not png",
        ),
        ("image/*", "not image/*"),
        ("image/png image/png", "'image/png' appears more than once"),
        ("", "accept must list 1 to 32 media types"),
        (
            "image/svg+xml application/pdf",
            "a page shows image/svg+xml, image/png, image/jpeg, image/gif, "
            "not application/pdf",
        ),
    ],
)
def test_an_invalid_accept_list_is_reported_at_its_host(
    accept: str, problem: str
) -> None:
    page = _page(
        f'<marimo-output value="chart" accept="{accept}"></marimo-output>\r\n'
        '<marimo-output value="table" accept="image/png"></marimo-output>'
    )

    sites, (diagnostic,) = html_sites(ENTRY, page)

    assert [site.targets for site in sites] == [("table",)]
    assert diagnostic.code == "projection-accept-invalid"
    assert problem in diagnostic.message
    assert diagnostic.source == SourceLocation(ENTRY, 4, 1)


def test_only_output_hosts_accept_media_types() -> None:
    page = _page('<marimo-cell name="summary" accept="image/png"></marimo-cell>')

    sites, (diagnostic,) = html_sites(ENTRY, page)

    assert sites == ()
    assert diagnostic.code == "projection-accept-invalid"
    assert "only <marimo-output> hosts accept media types" in diagnostic.message


def test_an_output_host_that_selects_its_target_at_runtime_declares_no_accept(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = _page(
        '<marimo-output value="chart" data-marimo-allow="*" accept="image/png">'
        "</marimo-output>"
    )
    project, _provider = _project(tmp_path, monkeypatch, page)

    diagnostics = inspect_view_project_sync(project).diagnostics

    (problem,) = (
        item for item in diagnostics if item.code == "projection-accept-invalid"
    )
    assert problem.severity == "error"
    assert problem.source == SourceLocation(ENTRY, 4, 1)


def test_hosts_of_one_output_accept_the_same_media_types(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = _page(
        '<marimo-output value="chart" accept="image/svg+xml"></marimo-output>\r\n'
        '<marimo-output value="chart"></marimo-output>'
    )
    project, _provider = _project(tmp_path, monkeypatch, page)

    diagnostics = inspect_view_project_sync(project).diagnostics

    (conflict,) = (
        item for item in diagnostics if item.code == "output-accept-conflict"
    )
    assert conflict.severity == "error"
    assert conflict.source == SourceLocation(ENTRY, 5, 1)
    assert conflict.message == (
        "chart is read as marimo's output here and as image/svg+xml at index.html:4."
    )


def test_accept_conflicts_report_each_host_once() -> None:
    targets = tuple(f"chart_{index}" for index in range(100))
    sites = tuple(
        ProjectionSite(
            "output",
            targets,
            SourceLocation(ENTRY, line, 1),
            line,
            ("image/png",) if line % 2 else ("image/svg+xml",),
        )
        for line in range(1, 6)
    )

    conflicts = accept_diagnostics(sites, ())

    assert [item.source.line for item in conflicts if item.source] == [2, 4]
