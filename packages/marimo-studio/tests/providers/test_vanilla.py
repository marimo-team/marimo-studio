from __future__ import annotations

from dataclasses import replace
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath

import pytest

from marimo_studio._views.inspection import inspection_request
from marimo_studio._workspace.project_manifest import (
    encode_view_manifest,
    load_view_project,
)
from marimo_studio.view_providers import StarterContext, ViewProject
from marimo_studio.view_providers._bundled.vanilla import provider

from ..provider_test_support import provider_build_request


def _write_files(root: Path, files: dict[PurePosixPath, bytes]) -> ViewProject:
    for relative, content in files.items():
        path = root.joinpath(*relative.parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    (root / "view.toml").write_text(
        encode_view_manifest("marimo-studio/vanilla"),
        encoding="utf-8",
    )
    return replace(load_view_project(root), options={"entrypoint": "index.html"})


def _project(tmp_path: Path) -> ViewProject:
    files = provider.create(
        provider.starters()[0],
        StarterContext("overview", "nga"),
    )
    return _write_files(tmp_path / "overview", dict(files))


class _ProjectionTags(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[tuple[str, dict[str, str | None]]] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        attributes = dict(attrs)
        if tag in {"marimo-cell", "marimo-output"} or "mo-value" in attributes:
            self.tags.append((tag, attributes))

    handle_startendtag = handle_starttag


@pytest.mark.parametrize(
    "body",
    (
        '<main id="app-shell"><marimo-cell name="controls" '
        'name="details"></marimo-cell></main>',
        '<main id="content" ID="app-shell"></main>',
    ),
)
def test_vanilla_rejects_duplicate_projection_and_shell_attributes(
    tmp_path: Path,
    body: str,
) -> None:
    project = _project(tmp_path)
    source = project.root / "index.html"
    source.write_text(
        f"""<!doctype html>
<html lang="en">
  <head><title>Duplicate attribute</title></head>
  <body>{body}</body>
</html>
""",
        encoding="utf-8",
    )

    inspection = provider.inspect(inspection_request(project))

    assert [item.code for item in inspection.diagnostics] == ["entry-document-invalid"]
    assert "Duplicate HTML attribute" in inspection.diagnostics[0].message


def test_vanilla_projection_diagnostics_name_the_authored_attributes(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    cases = (
        (
            '<marimo-cell target="summary"></marimo-cell>',
            "<marimo-cell> requires a non-empty name.",
        ),
        (
            '<marimo-output name="summary"></marimo-output>',
            "<marimo-output> requires a non-empty value.",
        ),
        ("<span mo-value></span>", "mo-value requires a non-empty selector."),
    )

    for projection, message in cases:
        (project.root / "index.html").write_text(
            f"""<!doctype html>
<html>
  <body>
    <main id="app-shell">
      {projection}
    </main>
  </body>
</html>
""",
            encoding="utf-8",
        )

        diagnostic = provider.inspect(inspection_request(project)).diagnostics[0]

        assert diagnostic.message == message
        assert 'Use <marimo-cell name="...">' in diagnostic.hint
        assert diagnostic.source is not None
        assert diagnostic.source.line == 5


def test_vanilla_instruments_exact_parser_sites(tmp_path: Path) -> None:
    project = _project(tmp_path)
    source = project.root / "index.html"
    source.write_text(
        """<!doctype html>
<html lang="en">
  <head>
    <title>Quoted &gt; text</title>
    <script>
      const fake = '<marimo-cell name="script > fake"' +
        ' data-marimo-studio-site="script">';
    </script>
    <style>.fake::after { content: '<span mo-value="style.fake">'; }</style>
  </head>
  <body>
    <!--
      <marimo-output value="comment.fake"
        data-marimo-studio-site="comment"></marimo-output>
    -->
    <main id="app-shell" aria-label="😀 > plain">
      <marimo-cell title="1 > 0" name=" controls "></marimo-cell>
      <marimo-output value=" report.total " data-label="x > y" />
      <span data-label=">" mo-value=" report.total "></span>
      <span mo-value="report.total"></span>
    </main>
  </body>
</html>
""",
        encoding="utf-8",
    )

    inspection = provider.inspect(inspection_request(project))

    assert inspection.diagnostics == ()
    assert [(site.kind, site.allowed_targets) for site in inspection.mounts] == [
        ("cell", ("controls",)),
        ("output", ("report.total",)),
        ("value", ("report.total",)),
        ("value", ("report.total",)),
    ]
    assert len({site.id for site in inspection.mounts}) == 4

    files = project.root / ".artifacts" / ".staging" / "test" / "files"
    files.mkdir(parents=True)
    report = provider.build(provider_build_request(project, inspection, files))

    assert report.document is not None
    built = (files / "index.html").read_text(encoding="utf-8")
    assert '<marimo-cell name="script > fake"' in built
    assert 'data-marimo-studio-site="script">' in built
    assert '<span mo-value="style.fake">' in built
    assert '<marimo-output value="comment.fake"' in built
    assert 'data-marimo-studio-site="comment"></marimo-output>' in built
    parser = _ProjectionTags()
    parser.feed(built)
    assert [attributes["data-marimo-studio-site"] for _, attributes in parser.tags] == [
        site.id for site in inspection.mounts
    ]


def test_vanilla_rejects_authored_mount_declaration_id(tmp_path: Path) -> None:
    project = _project(tmp_path)
    source = project.root / "index.html"
    source.write_text(
        source.read_text(encoding="utf-8").replace(
            '<main id="app-shell"',
            '<main id="app-shell" data-marimo-studio-site="authored"',
        ),
        encoding="utf-8",
    )

    inspection = provider.inspect(inspection_request(project))

    assert [item.code for item in inspection.diagnostics] == ["entry-document-invalid"]
    assert "data-marimo-studio-site is reserved" in inspection.diagnostics[0].message


@pytest.mark.parametrize(
    "entrypoint",
    (
        "index.txt",
        "../index.html",
    ),
)
def test_vanilla_entrypoint_must_be_a_normalized_html_path(
    tmp_path: Path,
    entrypoint: str,
) -> None:
    project = replace(_project(tmp_path), options={"entrypoint": entrypoint})

    inspection = provider.inspect(inspection_request(project))

    assert [item.code for item in inspection.diagnostics] == [
        "provider-options-invalid"
    ]


def test_vanilla_rejects_symlinked_entrypoint(tmp_path: Path) -> None:
    project = _project(tmp_path)
    entrypoint = project.root / "index.html"
    outside = tmp_path / "outside.html"
    outside.write_text(entrypoint.read_text(encoding="utf-8"), encoding="utf-8")
    entrypoint.unlink()
    entrypoint.symlink_to(outside)

    inspection = provider.inspect(inspection_request(project))

    assert [item.code for item in inspection.diagnostics] == ["entry-document-invalid"]
    assert "symlink" in inspection.diagnostics[0].message


@pytest.mark.parametrize(
    "resource",
    (
        '<link rel="stylesheet" href="app.css" />',
        '<link rel="modulepreload" href="scripts/app.js" />',
        '<script type="module" src="scripts/app.js"></script>',
        '<img src="images/chart.png" alt="Chart" />',
        "<style>.chart { background: url(images/chart.png) }</style>",
        '<div style="background: url(images/chart.png)"></div>',
        '<img srcset="images/small.png 1x, images/large.png 2x" />',
        '<source srcset="https://cdn.example.test/small.png 1x, '
        'images/large.png 2x" />',
        '<link rel="preload" as="image" imagesrcset="images/small.png 1x" />',
        '<svg><image href="images/chart.png" /></svg>',
        '<svg><feImage xlink:href="images/chart.png" /></svg>',
    ),
)
def test_vanilla_rejects_fetched_local_resources(
    tmp_path: Path,
    resource: str,
) -> None:
    project = _project(tmp_path)
    source = project.root / "index.html"
    source.write_text(
        source.read_text(encoding="utf-8").replace("</head>", f"{resource}</head>"),
        encoding="utf-8",
    )

    inspection = provider.inspect(inspection_request(project))

    assert [item.code for item in inspection.diagnostics] == [
        "local-resource-unsupported"
    ]
    assert "provider for multi-file projects" in inspection.diagnostics[0].message
    assert inspection.diagnostics[0].source is not None


def test_vanilla_allows_document_navigation_and_remote_resources(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    source = project.root / "index.html"
    source.write_text(
        source.read_text(encoding="utf-8")
        .replace(
            "</head>",
            """<script src="https://cdn.example.test/app.js"></script>
            <style>
              @import "https://cdn.example.test/app.css";
              .data { background: url(data:image/svg+xml;base64,PHN2Zy8+) }
              .fragment { background: url(#gradient) }
              .responsive { background: image-set(
                "https://cdn.example.test/chart.png" 1x,
                "data:image/png;base64,iVBORw0KGgo=" 2x
              ) }
              .literal::after { content: "url(images/not-a-resource.png)" }
              /* url(images/not-a-resource.png) */
            </style>
            <img srcset="https://cdn.example.test/small.png 1x,
              data:image/png;base64,iVBORw0KGgo= 2x" />
            </head>""",
        )
        .replace(
            "</main>",
            '<a href="details.html">Details</a></main>',
        ),
        encoding="utf-8",
    )

    inspection = provider.inspect(inspection_request(project))

    assert inspection.diagnostics == ()


def test_vanilla_reports_malformed_resource_urls_as_project_diagnostics(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    source = project.root / "index.html"
    source.write_text(
        source.read_text(encoding="utf-8").replace(
            "</head>",
            '<style>body { background: url("http://[") }</style></head>',
        ),
        encoding="utf-8",
    )

    inspection = provider.inspect(inspection_request(project))

    assert [item.code for item in inspection.diagnostics] == ["entry-document-invalid"]
    assert "Invalid resource URL" in inspection.diagnostics[0].message


def test_vanilla_exposes_instructions_outside_the_build_inputs(tmp_path: Path) -> None:
    project = _project(tmp_path)
    (project.root / ".env").write_text("TOKEN=secret\n", encoding="utf-8")
    (project.root / "DESIGN.md").write_text("# Page design\n", encoding="utf-8")

    inspection = provider.inspect(inspection_request(project))
    files = project.root / ".artifacts" / ".staging" / "single" / "files"
    files.mkdir(parents=True)
    report = provider.build(provider_build_request(project, inspection, files))

    assert [item.path.as_posix() for item in inspection.editor_documents] == [
        "index.html",
        "AGENTS.md",
        "DESIGN.md",
    ]
    assert [item.to_dict() for item in inspection.input_scope] == [
        {"path": "view.toml", "kind": "file"},
        {"path": "index.html", "kind": "file"},
    ]
    assert report.document == PurePosixPath("index.html")
    assert [
        path.relative_to(files).as_posix()
        for path in files.rglob("*")
        if path.is_file()
    ] == ["index.html"]


def test_vanilla_build_observes_cancellation_before_copying(tmp_path: Path) -> None:
    project = _project(tmp_path)
    inspection = provider.inspect(inspection_request(project))
    files = project.root / ".artifacts" / ".staging" / "cancelled" / "files"
    files.mkdir(parents=True)
    request = provider_build_request(project, inspection, files)
    request.cancellation.cancel()

    result = provider.build(request)

    assert result.document is None
    assert [diagnostic.code for diagnostic in result.diagnostics] == ["build-cancelled"]
    assert tuple(files.iterdir()) == ()
