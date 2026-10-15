from __future__ import annotations

import sys
from pathlib import Path, PurePosixPath

import pytest

from marimo_studio._artifacts.repository import (
    read_artifact_revision,
    read_profile_state,
)
from marimo_studio._views.build import build_view_project_sync
from marimo_studio._workspace.project_manifest import (
    CatalogProject,
    encode_view_manifest,
)
from marimo_studio.errors import ConfigurationError, ViewProjectError
from marimo_studio.view_providers import (
    BuildInput,
    BuildRequest,
    BuildResult,
    InspectionRequest,
    ProjectInspection,
    ProviderAvailability,
    Render,
    RenderFile,
    RenderRequest,
    RenderResult,
    RenderValue,
    SourceDocument,
    SourceLocation,
    ViewProject,
    copy_inputs,
    render_page,
)
from marimo_studio.view_providers._host.registry import ProviderRegistry

from ..artifact_test_support import manifest_path, read_json, write_json
from ..helpers import catalog_project
from ..provider_test_support import (
    ProviderStub,
    candidate,
    install_registry,
    publish,
)

TEMPLATE = PurePosixPath("card.txt")
SUMMARY = PurePosixPath("summary.txt")
MANIFEST = PurePosixPath("view.toml")
PAGE = PurePosixPath("index.html")


class PageProvider(ProviderStub):
    """Keep card.txt as the template of its render on a generated page."""

    def __init__(self) -> None:
        super().__init__("test-card/card", "default")
        self.renders: tuple[Render, ...] = (
            Render(
                TEMPLATE,
                values=(RenderValue("total", SourceLocation(TEMPLATE, 1, 1)),),
            ),
        )
        self.page: str | None = None
        self.entry = PAGE

    def inspect(self, request: InspectionRequest) -> ProjectInspection:
        del request
        return ProjectInspection(
            documents=(SourceDocument(TEMPLATE, "plaintext", "edit"),),
            inputs=(
                BuildInput(TEMPLATE, "file"),
                BuildInput(SUMMARY, "file"),
                BuildInput(MANIFEST, "file"),
            ),
            renders=self.renders,
        )

    def build(self, request: BuildRequest) -> BuildResult:
        copy_inputs(request, request.template_root)
        if self.page is None:
            render_page(request, TEMPLATE)
        else:
            request.staging_root.joinpath(self.entry).write_text(
                self.page, encoding="utf-8"
            )
        return BuildResult(self.entry)


class CardProvider(PageProvider):
    """Render card.txt as an SVG card."""

    def render(self, request: RenderRequest) -> RenderResult:
        text = request.template_root.joinpath(*request.source.parts).read_text(
            encoding="utf-8"
        )
        card = PurePosixPath("card.svg")
        request.output_root.joinpath(card).write_text(
            f'<svg xmlns="http://www.w3.org/2000/svg"><text>{text}</text></svg>',
            encoding="utf-8",
        )
        return RenderResult((RenderFile(card, "image/svg+xml"),), main=card)


def _project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider: PageProvider,
    template: str = "Total ready",
) -> CatalogProject:
    registry = ProviderRegistry(
        (candidate("card", provider, distribution="test-card"),)
    )
    install_registry(monkeypatch, registry)
    root = tmp_path / "card"
    root.mkdir()
    key = registry.ids[0]
    root.joinpath("view.toml").write_text(encode_view_manifest(key), encoding="utf-8")
    root.joinpath(TEMPLATE).write_text(template, encoding="utf-8")
    root.joinpath(SUMMARY).write_text("Summary", encoding="utf-8")
    return catalog_project(ViewProject("card", root, root / "view.toml", key, {}))


def _failure_codes(project: CatalogProject) -> list[str]:
    with pytest.raises(ViewProjectError):
        build_view_project_sync(project)
    state = read_profile_state(project, "development")
    assert state is not None
    return [item.code for item in state.build.diagnostics]


def test_a_build_publishes_the_page_and_keeps_the_template_private(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path, monkeypatch, CardProvider(), "Total ready")

    published = publish(project)

    assert set(published.files) == {PAGE}
    assert '<marimo-output render="card.txt"></marimo-output>' in (
        published.files[PAGE].decode()
    )
    with build_view_project_sync(project) as lease:
        template = lease.artifact.template
        copy = tmp_path / "template-copy"
        lease.copy_template(copy)
    assert template is not None
    assert [item.path for item in template.files] == [TEMPLATE, SUMMARY]
    assert copy.joinpath(TEMPLATE).read_text(encoding="utf-8") == "Total ready"


def test_each_render_read_publishes_a_site_named_by_its_render(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = CardProvider()
    read = RenderValue("total", SourceLocation(TEMPLATE, 1, 1))
    provider.renders = (
        Render(TEMPLATE, values=(read, read)),
        Render(SUMMARY, values=(read,)),
    )
    provider.page = (
        '<!doctype html><html><head></head><body><main id="app-shell">'
        '<marimo-output render="card.txt"></marimo-output>'
        '<marimo-output render="summary.txt"></marimo-output>'
        "</main></body></html>"
    )
    project = _project(tmp_path, monkeypatch, provider)

    published = publish(project)

    assert sorted(
        (site.render, site.kind, site.targets) for site in published.sites
    ) == [
        (TEMPLATE, "value", ("total",)),
        (SUMMARY, "value", ("total",)),
    ]
    assert len({site.id for site in published.sites}) == 2


def test_the_artifact_manifest_records_each_render_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path, monkeypatch, CardProvider())

    with build_view_project_sync(project) as lease:
        manifest = read_json(manifest_path(lease.artifact))
        renders = lease.artifact.template.renders if lease.artifact.template else ()

    assert manifest["schema"] == 4
    assert manifest["template"]["renders"] == ["card.txt"]
    assert renders == (TEMPLATE,)


def test_the_artifact_manifest_rejects_a_read_of_an_unpublished_render(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path, monkeypatch, CardProvider())
    with build_view_project_sync(project) as lease:
        artifact = lease.artifact
    path = manifest_path(artifact)
    manifest = read_json(path)
    manifest["sites"][0]["render"] = "summary.txt"
    write_json(path, manifest)

    with pytest.raises(ConfigurationError, match="names a render the artifact"):
        read_artifact_revision(project, artifact.artifact_revision)


def test_a_page_that_shows_an_undeclared_render_fails_the_build(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = CardProvider()
    provider.page = (
        '<!doctype html><html><head></head><body><main id="app-shell">\n'
        '<marimo-output render="slides.typ"></marimo-output>\n'
        "</main></body></html>"
    )
    project = _project(tmp_path, monkeypatch, provider)

    with pytest.raises(ViewProjectError):
        build_view_project_sync(project)

    state = read_profile_state(project, "development")
    assert state is not None
    (diagnostic,) = state.build.diagnostics
    assert diagnostic.code == "render-unknown"
    assert diagnostic.message == (
        "index.html:2:1: the page shows the render of slides.typ, "
        "which the view does not render."
    )
    assert diagnostic.hint == "Show a file the view renders: card.txt."


def test_a_build_entry_must_be_an_html_page(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = CardProvider()
    provider.entry = PurePosixPath("card.svg")
    provider.page = '<svg xmlns="http://www.w3.org/2000/svg"></svg>'
    project = _project(tmp_path, monkeypatch, provider)

    with pytest.raises(ViewProjectError):
        build_view_project_sync(project)

    state = read_profile_state(project, "development")
    assert state is not None
    (diagnostic,) = state.build.diagnostics
    assert diagnostic.code == "provider-build-failed"
    assert "returned 'card.svg'. A build returns an HTML page" in diagnostic.message


def test_a_view_that_declares_renders_needs_a_provider_with_render(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path, monkeypatch, PageProvider())

    assert _failure_codes(project) == ["renderer-missing"]


class LinkingCardProvider(CardProvider):
    """Build a template with a symlink in it."""

    def build(self, request: BuildRequest) -> BuildResult:
        result = super().build(request)
        request.template_root.joinpath("link.txt").symlink_to(TEMPLATE.name)
        return result


@pytest.mark.skipif(sys.platform == "win32", reason="creates a POSIX symlink")
def test_a_template_with_a_symlink_fails_the_build_at_the_provider_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path, monkeypatch, LinkingCardProvider())

    with pytest.raises(ViewProjectError):
        build_view_project_sync(project)

    state = read_profile_state(project, "development")
    assert state is not None
    (diagnostic,) = state.build.diagnostics
    assert diagnostic.code == "artifact-validation-failed"
    assert diagnostic.message == "Artifact output contains a symlink: link.txt"
    assert diagnostic.hint == "Fix the provider output and build the view again."


def test_a_renderer_upgrade_changes_the_artifact_revision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = CardProvider()
    project = _project(tmp_path, monkeypatch, provider, "Card")
    with build_view_project_sync(project) as lease:
        first = lease.artifact
    monkeypatch.setattr(
        provider,
        "availability",
        lambda: ProviderAvailability(True, version="2.0.0"),
    )

    with build_view_project_sync(project) as lease:
        second = lease.artifact

    assert first.files == second.files
    assert first.template is not None and second.template is not None
    assert first.template.files == second.template.files
    assert first.artifact_revision != second.artifact_revision


def test_the_artifact_manifest_rejects_a_template_without_its_render_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path, monkeypatch, CardProvider())
    with build_view_project_sync(project) as lease:
        artifact = lease.artifact
    path = manifest_path(artifact)
    manifest = read_json(path)
    (source,) = manifest["template"]["renders"]
    manifest["template"]["files"] = [
        item for item in manifest["template"]["files"] if item["path"] != source
    ]
    write_json(path, manifest)

    with pytest.raises(ConfigurationError, match="contain each render source"):
        read_artifact_revision(project, artifact.artifact_revision)
