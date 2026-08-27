from __future__ import annotations

from pathlib import Path

import marimo
import pytest

from marimo_studio._views.api import bind_cell, prepare_view
from marimo_studio._views.resolve import resolve_studio
from marimo_studio._workspace import load_studio
from marimo_studio.errors import (
    ConfigurationError,
)

from .workspace_test_support import (
    _shell,
)


def test_symbolic_projections_include_each_valid_view(notebook_path: Path) -> None:
    prepare_view(notebook_path)
    studio = load_studio(notebook_path)
    prepare_view(notebook_path, "executive")
    studio = load_studio(notebook_path)
    _shell(
        studio,
        "dashboard",
        '<span mo-value="doubled"></span>'
        '<marimo-output value="doubled"></marimo-output>',
    )
    _shell(
        studio,
        "executive",
        '<span mo-value="x"></span><marimo-output value="x"></marimo-output>',
    )

    resolved = resolve_studio(load_studio(notebook_path))
    assert {
        projection.request.target
        for view in resolved.views.values()
        for projection in view.projections
        if projection.kind == "value"
    } == {"doubled", "x"}
    assert {
        projection.request.target
        for view in resolved.views.values()
        for projection in view.projections
        if projection.kind == "output"
    } == {"doubled", "x"}


def test_output_projection_binds_to_the_defining_cell(notebook_path: Path) -> None:
    prepare_view(notebook_path)
    studio = load_studio(notebook_path)
    _shell(
        studio,
        "dashboard",
        '<marimo-output value="doubled"></marimo-output>',
    )

    view = resolve_studio(load_studio(notebook_path)).view("dashboard")

    projection = next(
        item
        for item in view.projections
        if item.kind == "output" and item.request.target == "doubled"
    )
    assert (
        projection.producer
        == resolve_studio(load_studio(notebook_path)).notebook.cells[1].ref
    )
    assert projection.source.line > 0


def test_symbolic_resolution_ignores_an_invalid_unselected_view(
    notebook_path: Path,
) -> None:
    prepare_view(notebook_path)
    studio = load_studio(notebook_path)
    _shell(studio, "dashboard", '<span mo-value="doubled"></span>')
    prepare_view(notebook_path, "draft")
    studio = load_studio(notebook_path)
    _shell(studio, "draft", '<span mo-value="doubled + 1"></span>')

    resolved = resolve_studio(load_studio(notebook_path), view_name="dashboard")
    assert [item.request.target for item in resolved.view().projections] == ["doubled"]


@pytest.mark.parametrize(
    ("template", "message"),
    [
        ("<html><head></head><body></body></html>", "expected one element"),
        (
            '<html><head><body><main id="app-shell"></main>',
            "expected one <head>",
        ),
        (
            '<html><meta charset="utf-8"><head></head><body>'
            '<main id="app-shell"></main></body></html>',
            "followed by <head>",
        ),
        (
            '<main id="app-shell"></main><div id="app-shell"></div>',
            "expected one element",
        ),
        (
            '<main id="app-shell"></main><span mo-value="doubled"></span>',
            "inside #app-shell",
        ),
        (
            '<main id="app-shell"></main>'
            '<marimo-output value="doubled"></marimo-output>',
            "inside #app-shell",
        ),
        (
            '<main id="app-shell"><span mo-value="doubled + 1"></span></main>',
            "Invalid mo-value reference",
        ),
        (
            '<main id="app-shell"><marimo-output></marimo-output></main>',
            "requires a value reference",
        ),
        (
            '<main id="app-shell">'
            '<marimo-output value="doubled + 1"></marimo-output></main>',
            "Invalid marimo-output value",
        ),
        (
            "<main id='app-shell' data-marimo-studio-runtime></main>",
            "reserved runtime markup",
        ),
    ],
)
def test_each_view_enforces_the_projection_shell(
    notebook_path: Path,
    template: str,
    message: str,
) -> None:
    prepare_view(notebook_path)
    studio = load_studio(notebook_path)
    if not template.startswith("<html"):
        template = f"<html><head></head><body>{template}</body></html>"
    (studio.views["dashboard"].root / "index.html").write_text(
        template, encoding="utf-8"
    )

    with pytest.raises(ConfigurationError, match=message):
        resolve_studio(load_studio(notebook_path))


def test_view_reports_each_unresolved_projection_with_its_source(
    notebook_path: Path,
) -> None:
    prepare_view(notebook_path)
    studio = load_studio(notebook_path)
    (studio.views["dashboard"].root / "index.html").write_text(
        """\
<html>
<head></head>
<body>
<main id="app-shell">
  <marimo-cell name="missing"></marimo-cell>
  <span mo-value="absent.label"></span>
  <marimo-output value="missing_output"></marimo-output>
</main>
</body>
</html>
""",
        encoding="utf-8",
    )

    view = resolve_studio(load_studio(notebook_path)).view("dashboard")

    assert [item.code for item in view.diagnostics] == [
        "projection-cell-not-found",
        "projection-value-variable-not-found",
        "projection-output-variable-not-found",
    ]
    assert [item.target for item in view.diagnostics] == [
        "missing",
        "absent.label",
        "missing_output",
    ]
    assert [item.line for item in view.diagnostics] == [5, 6, 7]
    assert all(item.column == 3 for item in view.diagnostics)
    assert all(item.site_id for item in view.diagnostics)
    assert len({item.site_id for item in view.diagnostics}) == 3


def test_repeated_output_sites_survive_static_resolution(notebook_path: Path) -> None:
    prepare_view(notebook_path)
    studio = load_studio(notebook_path)
    _shell(
        studio,
        "dashboard",
        '<marimo-output value="doubled"></marimo-output>'
        '<marimo-output value="doubled"></marimo-output>',
    )

    view = resolve_studio(load_studio(notebook_path)).view("dashboard")
    assert [
        projection.request.target
        for projection in view.projections
        if projection.kind == "output"
    ] == ["doubled", "doubled"]


def test_view_accepts_at_most_one_hundred_output_selectors(
    notebook_path: Path,
) -> None:
    prepare_view(notebook_path)
    studio = load_studio(notebook_path)

    def outputs(count: int) -> str:
        return "".join(
            f'<marimo-output value="output_{index}"></marimo-output>'
            for index in range(count)
        )

    _shell(studio, "dashboard", outputs(100))

    resolve_studio(load_studio(notebook_path))

    _shell(studio, "dashboard", outputs(101))
    with pytest.raises(ConfigurationError, match="at most 100 output selectors"):
        resolve_studio(load_studio(notebook_path))


@pytest.mark.parametrize("name", ["health", "studio"])
def test_view_names_cannot_claim_application_routes(
    notebook_path: Path,
    name: str,
) -> None:
    prepare_view(notebook_path)
    with pytest.raises(ConfigurationError, match=f"{name!r} is reserved"):
        prepare_view(notebook_path, name)


def test_changed_binding_reports_one_recovery_path(notebook_path: Path) -> None:
    prepare_view(notebook_path)
    studio = load_studio(notebook_path)
    bind_cell(studio, "result", 1)
    _shell(studio, "dashboard", '<marimo-cell name="result"></marimo-cell>')
    notebook_path.write_text(
        notebook_path.read_text(encoding="utf-8").replace(
            "doubled = x * 2",
            "doubled = x * 3",
        ),
        encoding="utf-8",
    )

    resolved = resolve_studio(load_studio(notebook_path))

    assert "result" not in resolved.aliases
    diagnostic = resolved.view("dashboard").diagnostics[0]
    assert diagnostic.code == "cell-binding-stale"
    assert diagnostic.target == "result"
    assert "--overwrite" in diagnostic.hint


def test_native_cell_name_supersedes_a_stale_configured_alias(
    notebook_path: Path,
) -> None:
    prepare_view(notebook_path)
    studio = load_studio(notebook_path)
    bind_cell(studio, "result", 1)
    _shell(studio, "dashboard", '<marimo-cell name="result"></marimo-cell>')
    source = notebook_path.read_text(encoding="utf-8")
    source = source.replace(
        "@app.cell\ndef _(x):",
        "@app.cell\ndef result(x):",
        1,
    ).replace("doubled = x * 2", "doubled = x * 3")
    notebook_path.write_text(source, encoding="utf-8")

    resolved = resolve_studio(load_studio(notebook_path))

    assert resolved.aliases["result"].name == "result"
    assert resolved.view("dashboard").diagnostics == ()


def test_binding_survives_reorder_and_rejects_ambiguous_serialization(
    tmp_path: Path,
) -> None:
    first = """\
@app.cell
def _(mo):
    mo.md(
        f\"\"\"
        ## Report
        \"\"\"
    )
    return
"""
    second = """\
@app.cell
def _(mo):
    mo.md(
        f\"\"\"
    ## Report
    \"\"\"
    )
    return
"""
    serialized = """\
@app.cell
def _(mo):
    mo.md(f\"\"\"
## Report
\"\"\")
    return
"""
    notebook = tmp_path / "strings.py"
    notebook.write_text(
        f"""\
import marimo

__generated_with = "{marimo.__version__}"
app = marimo.App()


{first}


{second}
""",
        encoding="utf-8",
    )
    prepare_view(notebook)
    studio = load_studio(notebook)
    bind_cell(studio, "report", 0)
    _shell(studio, "dashboard", '<marimo-cell name="report"></marimo-cell>')

    source = notebook.read_text(encoding="utf-8")
    source = source.replace(first, "__FIRST__", 1)
    source = source.replace(second, first, 1)
    notebook.write_text(source.replace("__FIRST__", second, 1), encoding="utf-8")

    reordered = resolve_studio(load_studio(notebook))
    assert reordered.aliases["report"].index == 1

    source = notebook.read_text(encoding="utf-8")
    source = source.replace(first, serialized, 1).replace(second, serialized, 1)
    notebook.write_text(source, encoding="utf-8")

    ambiguous = resolve_studio(load_studio(notebook))

    assert "report" not in ambiguous.aliases
    diagnostic = ambiguous.view("dashboard").diagnostics[0]
    assert diagnostic.code == "cell-binding-ambiguous"
    assert diagnostic.target == "report"
