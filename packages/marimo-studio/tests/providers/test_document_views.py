from __future__ import annotations

import sys
from pathlib import Path, PurePosixPath

import pytest

import marimo_studio._views.documents as documents_module
from marimo_studio._artifacts.repository import read_profile_state
from marimo_studio._views.build import build_view_project_sync
from marimo_studio._workspace.project_manifest import encode_view_manifest
from marimo_studio.errors import ViewProjectError
from marimo_studio.view_providers import (
    BuildInput,
    BuildRequest,
    BuildResult,
    InspectionRequest,
    ProjectDiagnostic,
    ProjectInspection,
    ProjectionSite,
    ProviderAvailability,
    RenderRequest,
    RenderValue,
    SourceDocument,
    SourceLocation,
    ViewProject,
)
from marimo_studio.view_providers._host.registry import ProviderRegistry

from ..provider_test_support import (
    ProviderStub,
    candidate,
    install_registry,
    publish,
)

TEMPLATE = PurePosixPath("card.txt")
MANIFEST = PurePosixPath("view.toml")
SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="40">'
    '<text x="4" y="24">{}</text></svg>'
)


class CardProvider(ProviderStub):
    """Publish card.txt as an SVG card."""

    def __init__(self) -> None:
        super().__init__("test-card/card", "default")
        self.values: tuple[RenderValue, ...] = ()
        self.sites: tuple[ProjectionSite, ...] = ()
        self.document = PurePosixPath("card.svg")
        self.render_calls: list[dict[str, object]] = []
        self.render_error: str | None = None

    def inspect(self, request: InspectionRequest) -> ProjectInspection:
        del request
        return ProjectInspection(
            documents=(SourceDocument(TEMPLATE, "plaintext", "edit"),),
            inputs=(
                BuildInput(TEMPLATE, "file"),
                BuildInput(MANIFEST, "file"),
            ),
            sites=self.sites,
            diagnostics=(),
            render_values=self.values,
        )

    def build(self, request: BuildRequest) -> BuildResult:
        text = request.project.root.joinpath(TEMPLATE).read_text(encoding="utf-8")
        request.staging_root.joinpath(self.document).write_text(
            SVG.format(text),
            encoding="utf-8",
        )
        return BuildResult(self.document, ())


class RenderedCardProvider(CardProvider):
    """Keep card.txt as a template and render it with notebook values."""

    def build(self, request: BuildRequest) -> BuildResult:
        text = request.project.root.joinpath(TEMPLATE).read_text(encoding="utf-8")
        request.staging_root.joinpath(TEMPLATE).write_text(text, encoding="utf-8")
        return BuildResult(TEMPLATE, ())

    def render(self, request: RenderRequest) -> BuildResult:
        self.render_calls.append(dict(request.values))
        if self.render_error is not None:
            return BuildResult(
                None,
                (
                    ProjectDiagnostic(
                        "card-render-error",
                        "error",
                        self.render_error,
                        source=SourceLocation(TEMPLATE, 1, 1),
                    ),
                ),
            )
        template = request.template_root.joinpath(*request.document.parts)
        text = template.read_text(encoding="utf-8").format(
            **{key.replace(".", "_"): value for key, value in request.values.items()}
        )
        request.output_root.joinpath("card.svg").write_text(
            SVG.format(text),
            encoding="utf-8",
        )
        return BuildResult(PurePosixPath("card.svg"), ())


def _project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider: CardProvider,
    template: str,
) -> ViewProject:
    registry = ProviderRegistry(
        (candidate("card", provider, distribution="test-card"),)
    )
    install_registry(monkeypatch, registry)
    root = tmp_path / "card"
    root.mkdir()
    key = registry.ids[0]
    root.joinpath("view.toml").write_text(encode_view_manifest(key), encoding="utf-8")
    root.joinpath(TEMPLATE).write_text(template, encoding="utf-8")
    return ViewProject("card", root, root / "view.toml", key, {})


def _value(target: str) -> RenderValue:
    return RenderValue(target, SourceLocation(TEMPLATE, 1, 1))


def test_static_documents_publish_the_document_behind_a_viewer_page(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = CardProvider()
    project = _project(tmp_path, monkeypatch, provider, "Quarterly card")

    published = publish(project)

    assert set(published.files) == {
        PurePosixPath("index.html"),
        PurePosixPath("card.svg"),
    }
    assert b"Quarterly card" in published.files[PurePosixPath("card.svg")]
    shell = published.files[PurePosixPath("index.html")].decode()
    assert '<marimo-document src="card.svg" type="image/svg+xml">' in shell
    assert published.sites == ()


def test_rendered_documents_keep_their_template_private(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = RenderedCardProvider()
    provider.values = (_value("metrics.total"), _value("metrics.total"))
    project = _project(tmp_path, monkeypatch, provider, "Total ready")

    published = publish(project)

    assert provider.render_calls == [{}]
    assert set(published.files) == {
        PurePosixPath("index.html"),
        PurePosixPath("card.svg"),
    }
    with build_view_project_sync(project) as lease:
        assert lease.artifact.template is not None
        assert [item.path for item in lease.artifact.template.files] == [TEMPLATE]
        copy = tmp_path / "template-copy"
        lease.copy_template(copy)
        assert copy.joinpath(TEMPLATE).read_text(encoding="utf-8") == "Total ready"
    (site,) = published.sites
    assert site.targets == ("metrics.total",)
    shell = published.files[PurePosixPath("index.html")].decode()
    assert (
        f'<span hidden mo-value="metrics.total" data-marimo-studio-site="{site.id}">'
        in shell
    )
    assert "render>" in shell


@pytest.mark.parametrize(
    ("failure", "code"),
    (("diagnostic", "card-render-error"), ("exception", "document-render-failed")),
)
def test_a_failing_template_keeps_the_last_published_document(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
    code: str,
) -> None:
    provider = RenderedCardProvider()
    project = _project(tmp_path, monkeypatch, provider, "First")
    with build_view_project_sync(project) as lease:
        first = lease.artifact.artifact_revision
    if failure == "diagnostic":
        provider.render_error = "unknown variable: total"
    project.root.joinpath(TEMPLATE).write_text("Second {total}", encoding="utf-8")

    with pytest.raises(ViewProjectError):
        build_view_project_sync(project)

    state = read_profile_state(project, "development")
    assert state is not None and state.published is not None
    assert [item.code for item in state.build.diagnostics] == [code]
    assert state.published.artifact_revision == first


class LinkingCardProvider(RenderedCardProvider):
    """Build a template with a symlink in its output."""

    def build(self, request: BuildRequest) -> BuildResult:
        result = super().build(request)
        request.staging_root.joinpath("link.txt").symlink_to(TEMPLATE.name)
        return result


@pytest.mark.skipif(sys.platform == "win32", reason="creates a POSIX symlink")
def test_document_output_failures_name_the_provider_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path, monkeypatch, LinkingCardProvider(), "First")

    with pytest.raises(ViewProjectError):
        build_view_project_sync(project)

    state = read_profile_state(project, "development")
    assert state is not None
    (diagnostic,) = state.build.diagnostics
    assert diagnostic.code == "artifact-validation-failed"
    assert diagnostic.hint == "Fix the provider output and build the view again."


class SlowCardProvider(RenderedCardProvider):
    """Render with a command that outlasts the render deadline."""

    def render(self, request: RenderRequest) -> BuildResult:
        request.runner.run(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            cwd=request.template_root,
            timeout=request.command_timeout,
        )
        return super().render(request)


def test_a_render_past_its_deadline_names_the_limit_and_the_next_step(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(documents_module, "RENDER_COMMAND_TIMEOUT", 0.5)
    project = _project(tmp_path, monkeypatch, SlowCardProvider(), "First")

    with pytest.raises(ViewProjectError):
        build_view_project_sync(project)

    state = read_profile_state(project, "development")
    assert state is not None
    (diagnostic,) = state.build.diagnostics
    assert diagnostic.code == "document-render-failed"
    assert "0.5 second" in diagnostic.message
    assert "ProviderCommandError" not in diagnostic.message
    assert diagnostic.hint.startswith("Fix card.txt")


@pytest.mark.parametrize(
    ("renders", "configure", "code"),
    (
        (False, "values", "document-renderer-missing"),
        (True, "sites", "projection-site-unsupported"),
        (False, "unsupported-type", "document-type-unsupported"),
    ),
)
def test_document_builds_reject_bindings_they_cannot_serve(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    renders: bool,
    configure: str,
    code: str,
) -> None:
    provider = RenderedCardProvider() if renders else CardProvider()
    template = '<span mo-value="total"></span>'
    if configure == "values":
        provider.values = (_value("total"),)
    elif configure == "sites":
        provider.sites = (
            ProjectionSite(
                "value",
                ("total",),
                SourceLocation(TEMPLATE, 1, 1),
                template.index(">"),
            ),
        )
    else:
        provider.document = PurePosixPath("card.docx")
    project = _project(tmp_path, monkeypatch, provider, template)

    with pytest.raises(ViewProjectError):
        build_view_project_sync(project)

    state = read_profile_state(project, "development")
    assert state is not None
    assert [item.code for item in state.build.diagnostics] == [code]


def test_a_renderer_upgrade_changes_the_artifact_revision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = RenderedCardProvider()
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
