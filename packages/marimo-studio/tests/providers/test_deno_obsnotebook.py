"""Verify Notebook Kit source declarations and immutable Vite candidates."""

from __future__ import annotations

from pathlib import Path, PurePosixPath

import pytest

from marimo_studio._artifacts.repository import read_build_state
from marimo_studio._artifacts.retention import lease_published_artifact
from marimo_studio._views.build import publish_view
from marimo_studio.errors import ViewProjectError
from marimo_studio.view_providers._bundled.deno_obsnotebook import provider

from ..deno_provider_test_support import inspect_provider, project
from ..provider_test_support import provider_build_request

pytestmark = [pytest.mark.deno, pytest.mark.usefixtures("shared_deno_test_cache")]


def test_notebook_html_cells_and_template_declare_source_located_mounts(
    tmp_path: Path,
) -> None:
    root, view = project(tmp_path, provider, "marimo-studio/notebook-kit")
    source = root / "src/index.html"
    source.write_text(
        """<!doctype html>
<notebook>
  <title>Unicode 🌍</title>
  <script id="1" type="text/html" output="host">
    <span hidden mo-value=" total "></span>
    <marimo-cell name="controls"></marimo-cell>
    <marimo-output value="${selected}" data-marimo-allow="*"></marimo-output>
    <marimo-cell name="${ready ? 'metric' : 'controls'}"></marimo-cell>
    <marimo-cell name=${
      ready ? 'controls' : 'metric'
    } data-note="${note}"></marimo-cell>
    <marimo-output value="summary" ${attributes} ${otherAttrs}
      data-marimo-allow="*"></marimo-output>
    <p>${`nested ${1 + 2}`} 😀</p>
  </script>
  <script id="2" type="module">
    const text = '<marimo-cell name="not-a-host"></marimo-cell>';
  </script>
</notebook>
""",
        encoding="utf-8",
    )
    template = root / "src/page.tmpl"
    template.write_text(
        template.read_text().replace(
            "</main>", '<marimo-output value="summary"></marimo-output></main>'
        )
    )
    inspection = inspect_provider(provider, view)
    assert inspection.diagnostics == ()
    assert inspection.mounts[-1].source.path == PurePosixPath("src/page.tmpl")
    assert inspection.mounts[-1].allowed_targets == ("summary",)
    assert [
        (site.kind, site.allowed_targets, site.source.line)
        for site in inspection.mounts[:-1]
    ] == [
        ("value", ("total",), 5),
        ("cell", ("controls",), 6),
        ("output", None, 7),
        ("cell", ("metric", "controls"), 8),
        ("cell", ("controls", "metric"), 9),
        ("output", None, 12),
    ]
    documents = {item.path.as_posix(): item for item in inspection.editor_documents}
    assert documents["src/index.html"].access == "edit"
    assert documents["src/page.tmpl"].language == "html"
    assert documents["deno.lock"].access == "read"
    assert any(
        item.path == PurePosixPath("src") and item.kind == "directory"
        for item in inspection.input_scope
    )


@pytest.mark.parametrize(
    ("html", "code"),
    [
        (
            '<marimo-cell name="${selected}"></marimo-cell>',
            "projection-target-unbounded",
        ),
        (
            '<marimo-cell name="controls" data-marimo-studio-site="forged">'
            "</marimo-cell>",
            "projection-site-reserved",
        ),
        (
            '<marimo-output value="summary" mo-value="total"></marimo-output>',
            "projection-kind-conflict",
        ),
        (
            '<marimo-cell name="controls" ${attrs}></marimo-cell>',
            "projection-target-unbounded",
        ),
        (
            "<marimo-cell name=\"${ready ? 'metric' : 'controls'}\" ${attrs}>"
            "</marimo-cell>",
            "projection-target-unbounded",
        ),
        (
            "<marimo-cell name=\"${ready ? '' : 'controls'}\"></marimo-cell>",
            "projection-target-domain-invalid",
        ),
        (
            "<marimo-cell name=\"${ready ? '' : 'controls'}\" "
            'data-marimo-allow="*"></marimo-cell>',
            "projection-target-domain-invalid",
        ),
        ("<marimo-cell></marimo-cell>", "projection-target-missing"),
        (
            '<marimo-cell name="controls" data-marimo-allow="maybe"></marimo-cell>',
            "projection-wildcard-invalid",
        ),
    ],
)
def test_notebook_invalid_projections_fail_closed(
    tmp_path: Path, html: str, code: str
) -> None:
    root, view = project(tmp_path, provider, "marimo-studio/notebook-kit")
    (root / "src/index.html").write_text(
        f'<notebook><script type="text/html">{html}</script></notebook>',
        encoding="utf-8",
    )
    inspection = inspect_provider(provider, view)
    assert [item.code for item in inspection.diagnostics] == [code]
    assert inspection.mounts == ()


def test_notebook_failed_build_retains_publication_and_recovers(tmp_path: Path) -> None:
    root, view = project(tmp_path, provider, "marimo-studio/notebook-kit")
    source = root / "src/index.html"
    original = source.read_text(encoding="utf-8")
    with publish_view(view, "development") as first:
        assert source.read_text(encoding="utf-8") == original
        revision = first.artifact.artifact_revision
        document = first.read_text(first.artifact.document)
        source.write_text(
            original.replace(
                "</notebook>", '<script type="module">const =</script></notebook>'
            ),
            encoding="utf-8",
        )
        with pytest.raises(ViewProjectError):
            publish_view(view, "development")
        assert read_build_state(view, "development").phase == "failed"
        retained = lease_published_artifact(view, "development")
        assert retained is not None
        with retained:
            assert retained.artifact.artifact_revision == revision
            assert retained.read_text(retained.artifact.document) == document
        source.write_text(
            original.replace(
                "</notebook>",
                '<script type="text/html"><p>Recovered view</p></script></notebook>',
            ),
            encoding="utf-8",
        )
        with publish_view(view, "development") as recovered:
            assert recovered.artifact.artifact_revision != revision
            assert "Recovered view" in recovered.read_text(recovered.artifact.document)
        assert first.read_text(first.artifact.document) == document


def test_notebook_build_time_execution_reports_the_source_cell(tmp_path: Path) -> None:
    root, view = project(tmp_path, provider, "marimo-studio/notebook-kit")
    (root / "src/index.html").write_text(
        """<notebook>
<script type="text/x-python">print("build side effect")</script>
</notebook>
""",
        encoding="utf-8",
    )
    inspection = inspect_provider(provider, view)
    assert [item.code for item in inspection.diagnostics] == [
        "notebook-build-execution-unsupported"
    ]
    assert inspection.diagnostics[0].source is not None
    assert inspection.diagnostics[0].source.line == 2


def test_notebook_rejects_duplicate_authored_attributes_next_to_a_binding(
    tmp_path: Path,
) -> None:
    root, view = project(tmp_path, provider, "marimo-studio/notebook-kit")
    (root / "src/index.html").write_text(
        '<notebook><script type="text/html">'
        '<marimo-cell name="controls" name="${target}" data-marimo-allow="*">'
        "</marimo-cell></script></notebook>",
        encoding="utf-8",
    )
    inspection = inspect_provider(provider, view)
    assert [item.code for item in inspection.diagnostics] == ["notebook-html-invalid"]
    assert inspection.mounts == ()
    output = root / ".artifacts/.staging/invalid/files"
    output.mkdir(parents=True)
    result = provider.build(provider_build_request(view, inspection, output))
    assert result.document is None
    assert [item.code for item in result.diagnostics] == ["notebook-html-invalid"]
