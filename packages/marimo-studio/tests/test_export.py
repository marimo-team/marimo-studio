from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from marimo_studio._cli import cli
from marimo_studio.errors import StaticExportError
from marimo_studio.export import export_view
from marimo_studio.workspace import ensure_view

from .helpers import replace_app_shell


def _configured_view(notebook: Path) -> Path:
    setup = ensure_view(notebook)
    template = setup.root / "index.html"
    template.write_text(
        replace_app_shell(
            template.read_text(encoding="utf-8"),
            """
            <marimo-cell name="cell-2"></marimo-cell>
            <output mo-value="doubled"></output>
            <button
              hx-get="./_marimo-studio/views/dashboard/cells/cell-2"
              hx-target="#lazy-cell"
            >
              Load result
            </button>
            <div id="lazy-cell"></div>
            """,
        ),
        encoding="utf-8",
    )
    return setup.root


def test_export_view_writes_a_complete_static_bundle(
    notebook_path: Path,
    tmp_path: Path,
) -> None:
    view_root = _configured_view(notebook_path)
    public = notebook_path.parent / "public"
    public.mkdir()
    public.joinpath("sample.txt").write_text("public asset", encoding="utf-8")
    output = tmp_path / "site"

    result = export_view(notebook_path, output)

    config = json.loads(
        output.joinpath("_marimo-studio/views/dashboard/config").read_text(
            encoding="utf-8"
        )
    )
    document = result.entrypoint.read_text(encoding="utf-8")
    assert result.view == "dashboard"
    assert result.output == output
    assert result.files == sum(1 for path in output.rglob("*") if path.is_file())
    assert config["runtime"]["id"] == "wasm"
    assert config["runtime"]["available"] == ["wasm"]
    assert config["rootUrl"] == "./"
    assert config["supportUrl"] == "./_marimo-studio/views/dashboard"
    assert config["cellBindings"]["cell-2"]["kind"] == "id"
    assert config["valueBindings"]["doubled"]["variable"] == "doubled"
    code = config["runtime"]["data"]["code"]
    compile(code, "notebook.py", "exec")
    assert "def __marimo_studio_values" in code
    assert "[tool.marimo-studio]" not in code
    assert 'src="./_marimo-studio/assets/runtime.js"' in document
    assert 'href="./_marimo-studio/assets/runtime.css"' in document
    assert '"runtime":"wasm"' in document
    assert output.joinpath("_marimo-studio/views/dashboard/cells/cell-2").read_text(
        encoding="utf-8"
    ) == ('<marimo-cell name="cell-2"></marimo-cell>')
    assert (
        output.joinpath("_marimo-studio/views/dashboard/static/app.css").read_bytes()
        == view_root.joinpath("app.css").read_bytes()
    )
    assert output.joinpath("public/sample.txt").read_text(encoding="utf-8") == (
        "public asset"
    )
    assert output.joinpath("_marimo-studio/assets/runtime.js").is_file()
    assert output.joinpath(".nojekyll").is_file()


def test_export_view_replaces_an_existing_bundle_only_with_force(
    notebook_path: Path,
    tmp_path: Path,
) -> None:
    _configured_view(notebook_path)
    output = tmp_path / "site"
    export_view(notebook_path, output)
    output.joinpath("stale.txt").write_text("stale", encoding="utf-8")

    with pytest.raises(StaticExportError, match="Pass --force"):
        export_view(notebook_path, output)

    export_view(notebook_path, output, force=True)
    assert not output.joinpath("stale.txt").exists()
    assert output.joinpath("index.html").is_file()


def test_export_view_reports_unresolved_projections_before_writing(
    notebook_path: Path,
    tmp_path: Path,
) -> None:
    view_root = _configured_view(notebook_path)
    template = view_root / "index.html"
    template.write_text(
        replace_app_shell(
            template.read_text(encoding="utf-8"),
            '<marimo-cell name="missing"></marimo-cell>',
        ),
        encoding="utf-8",
    )
    output = tmp_path / "site"

    with pytest.raises(StaticExportError, match="unresolved projections"):
        export_view(notebook_path, output)

    assert not output.exists()


def test_export_view_rejects_an_output_that_contains_the_notebook(
    notebook_path: Path,
) -> None:
    _configured_view(notebook_path)

    with pytest.raises(StaticExportError, match="overlaps a static export source"):
        export_view(notebook_path, notebook_path.parent, force=True)

    assert notebook_path.is_file()


def test_export_command_reports_the_static_entrypoint(
    notebook_path: Path,
    tmp_path: Path,
) -> None:
    _configured_view(notebook_path)
    output = tmp_path / "site"

    result = CliRunner().invoke(
        cli,
        [
            "export",
            str(notebook_path),
            "--output",
            str(output),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema"] == 1
    assert payload["view"] == "dashboard"
    assert payload["runtime"] == "wasm"
    assert Path(payload["entrypoint"]) == output / "index.html"
    assert output.joinpath("index.html").is_file()
