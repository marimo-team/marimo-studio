from __future__ import annotations

from dataclasses import replace
from html.parser import HTMLParser
from pathlib import Path

import pytest

from marimo_studio._views.inspection import inspection_request
from marimo_studio.view_providers._bundled.vanilla import provider

from ..helpers import no_display_notebook_source
from ..provider_test_support import provider_build_request
from ._vanilla_test_support import _project


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


def test_vanilla_starter_exposes_its_generated_notebook_cell(tmp_path: Path) -> None:
    project = _project(tmp_path)

    inspection = provider.inspect(inspection_request(project))

    assert [(site.kind, site.allowed_targets) for site in inspection.mounts] == [
        ("cell", ("cell-2",)),
    ]


def test_vanilla_starter_builds_without_possible_output_cells(tmp_path: Path) -> None:
    tmp_path.joinpath("analysis.py").write_text(
        no_display_notebook_source(),
        encoding="utf-8",
    )
    project = _project(tmp_path)
    inspection = provider.inspect(inspection_request(project))
    files = project.root / ".artifacts" / ".staging" / "zero-display" / "files"
    files.mkdir(parents=True)

    report = provider.build(provider_build_request(project, inspection, files))

    assert inspection.diagnostics == ()
    assert inspection.mounts == ()
    assert report.document is not None


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


def test_vanilla_projection_diagnostics_locate_authored_sources(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    cases = (
        '<marimo-cell target="summary"></marimo-cell>',
        '<marimo-output name="summary"></marimo-output>',
        "<span mo-value></span>",
    )

    for projection in cases:
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

        assert diagnostic.code == "entry-document-invalid"
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


def test_vanilla_build_preserves_crlf_line_endings(tmp_path: Path) -> None:
    project = _project(tmp_path)
    source = project.root / "index.html"
    authored = source.read_bytes().replace(b"\n", b"\r\n")
    source.write_bytes(authored)
    inspection = provider.inspect(inspection_request(project))
    files = project.root / ".artifacts" / ".staging" / "crlf" / "files"
    files.mkdir(parents=True)

    provider.build(provider_build_request(project, inspection, files))

    built = (files / "index.html").read_bytes()
    assert b"\r\r\n" not in built
    assert built.count(b"\r\n") == authored.count(b"\r\n")


def test_vanilla_rejects_authored_runtime_attributes(tmp_path: Path) -> None:
    project = _project(tmp_path)
    source = project.root / "index.html"
    original = source.read_text(encoding="utf-8")
    replacements = (
        (
            '<main id="app-shell"',
            '<main id="app-shell" data-marimo-studio-site="authored"',
        ),
        (
            "</head>",
            '<script data-marimo-studio-source-revision="authored"></script></head>',
        ),
    )

    for target, replacement in replacements:
        source.write_text(
            original.replace(target, replacement),
            encoding="utf-8",
        )

        inspection = provider.inspect(inspection_request(project))

        assert [item.code for item in inspection.diagnostics] == [
            "entry-document-invalid"
        ]


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
