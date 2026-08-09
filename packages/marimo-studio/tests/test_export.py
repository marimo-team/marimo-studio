from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

import marimo_studio.export as export_module
from marimo_studio._cli import cli
from marimo_studio._workspace import load_studio
from marimo_studio.errors import StaticExportError
from marimo_studio.export import export_view
from marimo_studio.workspace import bind_cell, ensure_view

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
    view_root.joinpath("app.js").write_text(
        'import { message } from "./message.js";\nwindow.message = message;\n',
        encoding="utf-8",
    )
    view_root.joinpath("message.js").write_text(
        'export const message = "ready";\n',
        encoding="utf-8",
    )
    template = view_root / "index.html"
    template.write_text(
        template.read_text(encoding="utf-8").replace(
            "</head>",
            '<script type="module" src="app.js"></script>\n  </head>',
        ),
        encoding="utf-8",
    )
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
    assert config["publicRootUrl"] == "./"
    assert config["supportUrl"] == "./_marimo-studio/views/dashboard"
    assert config["cellBindings"]["cell-2"]["kind"] == "id"
    assert config["valueBindings"]["doubled"]["variable"] == "doubled"
    code = config["runtime"]["data"]["code"]
    compile(code, "notebook.py", "exec")
    assert "[tool.marimo-studio]" not in code
    assert 'src="./_marimo-studio/assets/runtime.js"' in document
    assert 'href="./_marimo-studio/assets/runtime.css"' in document
    assert '<base href="./">' in document
    assert '<script type="module" src="app.js"></script>' in document
    assert '"runtime":"wasm"' in document
    assert output.joinpath("_marimo-studio/views/dashboard/cells/cell-2").read_text(
        encoding="utf-8"
    ) == ('<marimo-cell name="cell-2"></marimo-cell>')
    assert (
        output.joinpath("app.css").read_bytes()
        == view_root.joinpath("app.css").read_bytes()
    )
    assert 'from "./message.js"' in output.joinpath("app.js").read_text(
        encoding="utf-8"
    )
    assert output.joinpath("message.js").read_text(encoding="utf-8") == (
        'export const message = "ready";\n'
    )
    assert output.joinpath("public/sample.txt").read_text(encoding="utf-8") == (
        "public asset"
    )
    assert output.joinpath("_marimo-studio/assets/runtime.js").is_file()
    assert output.joinpath(".nojekyll").is_file()


@pytest.mark.parametrize(
    ("relative", "message"),
    [
        ("_MARIMO-STUDIO/assets/runtime.js", "reserved Marimo or Studio route"),
        (".nojekyll", "owned by both"),
    ],
)
def test_export_view_rejects_view_assets_that_collide_with_generated_paths(
    notebook_path: Path,
    tmp_path: Path,
    relative: str,
    message: str,
) -> None:
    view_root = _configured_view(notebook_path)
    asset = view_root / relative
    asset.parent.mkdir(parents=True, exist_ok=True)
    asset.write_text("collision", encoding="utf-8")

    with pytest.raises(StaticExportError, match=message):
        export_view(notebook_path, tmp_path / "site")

    assert not (tmp_path / "site").exists()


def test_export_view_rejects_case_equivalent_cell_fragments(
    notebook_path: Path,
    tmp_path: Path,
) -> None:
    _configured_view(notebook_path)
    studio = load_studio(notebook_path)
    bind_cell(studio, "Result", 1)
    bind_cell(load_studio(notebook_path), "result", 1)
    template = load_studio(notebook_path).views["dashboard"].template
    template.write_text(
        replace_app_shell(
            template.read_text(encoding="utf-8"),
            '<marimo-cell name="Result"></marimo-cell>'
            '<marimo-cell name="result"></marimo-cell>',
        ),
        encoding="utf-8",
    )

    with pytest.raises(StaticExportError, match="owned by both"):
        export_view(notebook_path, tmp_path / "site")


def test_export_view_preserves_a_destination_created_during_generation(
    notebook_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configured_view(notebook_path)
    output = tmp_path / "site"
    commit_bundle = export_module._commit_bundle

    def create_destination(
        staged: Path,
        target: export_module._OutputTarget,
    ) -> None:
        output.mkdir()
        output.joinpath("concurrent.txt").write_text("keep", encoding="utf-8")
        commit_bundle(staged, target)

    monkeypatch.setattr(export_module, "_commit_bundle", create_destination)

    with pytest.raises(StaticExportError, match="Output changed"):
        export_view(notebook_path, output)

    assert output.joinpath("concurrent.txt").read_text(encoding="utf-8") == "keep"


def test_forced_export_preserves_a_destination_changed_during_generation(
    notebook_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configured_view(notebook_path)
    output = tmp_path / "site"
    export_view(notebook_path, output)
    commit_bundle = export_module._commit_bundle

    def change_destination(
        staged: Path,
        target: export_module._OutputTarget,
    ) -> None:
        output.joinpath("concurrent.txt").write_text("keep", encoding="utf-8")
        commit_bundle(staged, target)

    monkeypatch.setattr(export_module, "_commit_bundle", change_destination)

    with pytest.raises(StaticExportError, match="Output changed"):
        export_view(notebook_path, output, force=True)

    assert output.joinpath("concurrent.txt").read_text(encoding="utf-8") == "keep"


def test_forced_export_keeps_recovery_when_destination_is_reclaimed(
    notebook_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configured_view(notebook_path)
    output = tmp_path / "site"
    export_view(notebook_path, output)
    directory_identity = export_module._directory_identity

    def reclaim_destination(path: Path) -> tuple[tuple[object, ...], ...] | None:
        identity = directory_identity(path)
        if path.name == "previous":
            output.mkdir()
            output.joinpath("concurrent.txt").write_text("keep", encoding="utf-8")
            return (
                (*identity, ("changed",)) if identity is not None else (("changed",),)
            )
        return identity

    monkeypatch.setattr(export_module, "_directory_identity", reclaim_destination)

    with pytest.raises(StaticExportError, match="previous output is preserved"):
        export_view(notebook_path, output, force=True)

    assert output.joinpath("concurrent.txt").read_text(encoding="utf-8") == "keep"
    recoveries = tuple(tmp_path.glob(".site-recovery-*"))
    assert len(recoveries) == 1
    assert recoveries[0].joinpath("index.html").is_file()


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
