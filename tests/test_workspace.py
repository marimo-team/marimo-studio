from __future__ import annotations

import asyncio
from collections.abc import MutableMapping
from pathlib import Path

import marimo
import pytest

import marimo_studio._workspace.checks as checks_module
import marimo_studio._workspace.setup as workspace_setup
from marimo_studio._compat.kernel_values import (
    ValueReadError,
    ValueReadResult,
    _template_selectors,
)
from marimo_studio._compat.runtime_probe import RuntimeCell, RuntimeProbe
from marimo_studio._workspace import (
    bind_cell,
    check_runtime_studio,
    check_studio,
    ensure_view,
    load_studio,
    resolve_studio,
)
from marimo_studio._workspace.config import load_studio_definition
from marimo_studio._workspace.metadata import (
    read_notebook_metadata,
    update_notebook_config,
)
from marimo_studio._workspace.models import StudioConfig
from marimo_studio.errors import BindingError, ConfigurationError


def _shell(studio: StudioConfig, view_name: str, content: str) -> None:
    template = studio.views[view_name].template
    template.write_text(
        template.read_text(encoding="utf-8").replace(
            '<main id="app-shell"></main>',
            f'<main id="app-shell">{content}</main>',
        ),
        encoding="utf-8",
    )


def test_first_view_configures_the_notebook_in_place(notebook_path: Path) -> None:
    original = notebook_path.read_text(encoding="utf-8")

    result = ensure_view(notebook_path)
    studio = load_studio(notebook_path)
    document = read_notebook_metadata(notebook_path)

    assert result.studio == studio
    assert studio.uses_notebook_config
    assert studio.config_path == notebook_path
    assert studio.view_root == (
        notebook_path.parent / "__marimo__" / "studio" / notebook_path.stem
    )
    assert studio.views["dashboard"].template.is_file()
    assert document is not None
    assert document["tool"]["marimo-studio"]["default"] == "dashboard"
    assert "marimo-studio" in document["dependencies"]
    assert notebook_path.read_text(encoding="utf-8").endswith(original)


def test_setup_preserves_other_pep_723_metadata_and_notebook_body(
    notebook_path: Path,
) -> None:
    body = notebook_path.read_text(encoding="utf-8")
    notebook_path.write_text(
        """\
# /// script
# requires-python = ">=3.12"
# dependencies = ["polars>=1", "marimo-studio>=0"]
#
# [tool.marimo.runtime]
# auto_instantiate = true
# ///

"""
        + body,
        encoding="utf-8",
    )

    ensure_view(notebook_path, "finance")
    document = read_notebook_metadata(notebook_path)

    assert document is not None
    assert document["requires-python"] == ">=3.12"
    assert document["tool"]["marimo"]["runtime"]["auto_instantiate"] is True
    assert document["tool"]["marimo-studio"]["default"] == "finance"
    package_dependencies = [
        str(value)
        for value in document["dependencies"]
        if "marimo-studio" in str(value)
    ]
    assert package_dependencies == ["marimo-studio"]
    assert notebook_path.read_text(encoding="utf-8").endswith(body)


def test_setup_preserves_crlf_notebook_body(tmp_path: Path) -> None:
    notebook = tmp_path / "analysis.py"
    body = (
        "import marimo\r\n"
        f'__generated_with = "{marimo.__version__}"\r\n'
        "app = marimo.App()\r\n"
        "@app.cell\r\n"
        "def _():\r\n"
        "    value = 1\r\n"
        "    value\r\n"
        "    return (value,)\r\n"
    )
    notebook.write_bytes(body.encode())

    ensure_view(notebook)

    updated = notebook.read_bytes()
    assert updated.endswith(body.encode())
    assert b"\r\n" in updated
    assert b"\n" not in updated.replace(b"\r\n", b"")


def test_setup_preserves_shebang_and_encoding_cookie(tmp_path: Path) -> None:
    notebook = tmp_path / "analysis.py"
    source = (
        "#!/usr/bin/env python\n"
        "# -*- coding: utf-8 -*-\n"
        f'import marimo\n__generated_with = "{marimo.__version__}"\n'
        "app = marimo.App()\n"
        "@app.cell\n"
        "def _():\n"
        "    return\n"
    )
    notebook.write_text(source, encoding="utf-8")

    ensure_view(notebook)

    updated = notebook.read_text(encoding="utf-8")
    assert updated.startswith(
        "#!/usr/bin/env python\n# -*- coding: utf-8 -*-\n# /// script\n"
    )
    assert updated.endswith(source.split("# -*- coding: utf-8 -*-\n", 1)[1])


def test_setup_rolls_back_notebook_and_view_files_after_write_failure(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = notebook_path.read_bytes()
    write = workspace_setup.atomic_write_text
    calls = 0

    def fail_second_write(path: Path, content: str) -> None:
        nonlocal calls
        calls += 1
        write(path, content)
        if calls == 2:
            raise OSError("simulated write failure")

    monkeypatch.setattr(workspace_setup, "atomic_write_text", fail_second_write)

    with pytest.raises(OSError, match="simulated write failure"):
        ensure_view(notebook_path)

    assert notebook_path.read_bytes() == original
    assert not (notebook_path.parent / "__marimo__").exists()


def test_setup_converges_package_requirements_and_sources(
    notebook_path: Path,
) -> None:
    body = notebook_path.read_text(encoding="utf-8")
    notebook_path.write_text(
        """\
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "Marimo_Studio @ https://packages.example/widget.whl",
#   "humanize>=4",
#   "marimo.studio<1",
# ]
#
# [tool.uv.sources]
# Marimo_Studio = { git = "https://example.test/old.git" }
# humanize = { git = "https://example.test/humanize.git" }
# ///

"""
        + body,
        encoding="utf-8",
    )

    ensure_view(notebook_path)
    document = read_notebook_metadata(notebook_path)

    assert document is not None
    assert list(document["dependencies"]) == [
        "marimo-studio",
        "humanize>=4",
    ]
    assert dict(document["tool"]["uv"]["sources"]) == {
        "humanize": {"git": "https://example.test/humanize.git"}
    }
    assert notebook_path.read_text(encoding="utf-8").endswith(body)

    configured = notebook_path.read_bytes()
    repeated = ensure_view(notebook_path)

    assert notebook_path.read_bytes() == configured
    assert repeated.updated == ()


def test_setup_tightens_the_notebook_python_requirement(
    notebook_path: Path,
) -> None:
    body = notebook_path.read_text(encoding="utf-8")
    notebook_path.write_text(
        """\
# /// script
# requires-python = ">=3.10,<3.13"
# dependencies = []
# ///

"""
        + body,
        encoding="utf-8",
    )

    ensure_view(notebook_path)
    document = read_notebook_metadata(notebook_path)

    assert document is not None
    assert document["requires-python"] == ">=3.11,<3.13"


def test_setup_rejects_disjoint_python_requirements_before_mutation(
    notebook_path: Path,
) -> None:
    notebook_path.write_text(
        notebook_path.read_text(encoding="utf-8").replace(
            "import marimo",
            '# /// script\n# requires-python = "<3.11"\n'
            "# dependencies = []\n# ///\n\nimport marimo",
        ),
        encoding="utf-8",
    )
    original = notebook_path.read_bytes()

    with pytest.raises(ConfigurationError, match="do not overlap"):
        ensure_view(notebook_path)

    assert notebook_path.read_bytes() == original
    assert not (notebook_path.parent / "__marimo__").exists()


@pytest.mark.parametrize("name", ["notes.txt", "script.py"])
def test_setup_rejects_non_notebooks_without_mutation(
    tmp_path: Path,
    name: str,
) -> None:
    target = tmp_path / name
    target.write_text("answer = 42\n", encoding="utf-8")
    original = target.read_bytes()

    with pytest.raises(ConfigurationError):
        ensure_view(target)

    assert target.read_bytes() == original
    assert not (tmp_path / "__marimo__").exists()


def test_project_configuration_uses_the_notebook_local_view_directory(
    notebook_path: Path,
) -> None:
    project_root = notebook_path.parent
    notebook_dir = project_root / "notebooks"
    notebook_dir.mkdir()
    notebook = notebook_dir / notebook_path.name
    notebook.write_bytes(notebook_path.read_bytes())
    original = notebook.read_bytes()
    pyproject = project_root / "pyproject.toml"
    pyproject.write_text(
        f"""\
[project]
name = "analysis"
version = "0.0.1"
dependencies = ["marimo-studio==1.2.3"]

[tool.marimo-studio]
notebook = "notebooks/{notebook.name}"
default = "executive"

[tool.marimo-studio.cells]
""",
        encoding="utf-8",
    )

    ensure_view(notebook)
    studio = load_studio(notebook)

    assert studio.config_source == "pyproject"
    assert studio.config_path == pyproject
    assert studio.default_view == "executive"
    assert set(studio.views) == {"executive"}
    assert studio.view_root == notebook_dir / "__marimo__" / "studio" / notebook.stem
    assert notebook.read_bytes() == original


def test_notebooks_with_the_same_parent_have_independent_presentations(
    notebook_path: Path,
) -> None:
    second = notebook_path.with_name("forecast.py")
    second.write_text(notebook_path.read_text(encoding="utf-8"), encoding="utf-8")

    ensure_view(notebook_path, "dashboard")
    ensure_view(second, "forecast")

    first_studio = load_studio(notebook_path)
    second_studio = load_studio(second)
    assert first_studio.view_root != second_studio.view_root
    assert set(first_studio.views) == {"dashboard"}
    assert set(second_studio.views) == {"forecast"}


def test_directory_discovery_requires_an_explicit_notebook_on_conflict(
    notebook_path: Path,
) -> None:
    inline = notebook_path.with_name("inline.py")
    inline.write_text(notebook_path.read_text(encoding="utf-8"), encoding="utf-8")
    ensure_view(inline)
    (notebook_path.parent / "pyproject.toml").write_text(
        f"""\
[tool.marimo-studio]
notebook = "{notebook_path.name}"
default = "dashboard"
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="Pass a notebook path"):
        load_studio_definition(notebook_path.parent)

    assert load_studio_definition(inline).notebook == inline


def test_notebook_configuration_controls_session_preservation(
    notebook_path: Path,
) -> None:
    ensure_view(notebook_path)

    def preserve(config: MutableMapping[str, object]) -> None:
        config["preserve_session"] = True

    update_notebook_config(notebook_path, preserve)
    assert load_studio(notebook_path).preserve_session is True

    def invalidate(config: MutableMapping[str, object]) -> None:
        config["preserve_session"] = "yes"

    update_notebook_config(notebook_path, invalidate)
    with pytest.raises(ConfigurationError, match="preserve_session must be a boolean"):
        load_studio(notebook_path)


def test_named_views_share_notebook_bindings(notebook_path: Path) -> None:
    ensure_view(notebook_path)
    studio = load_studio(notebook_path)
    bound = bind_cell(studio, "result", 1)
    ensure_view(notebook_path, "executive")
    studio = load_studio(notebook_path)
    _shell(
        studio,
        "dashboard",
        '<marimo-cell name="result"></marimo-cell><span mo-value="doubled"></span>',
    )
    _shell(
        studio,
        "executive",
        '<marimo-cell name="result"></marimo-cell><span mo-value="x"></span>',
    )

    resolved = resolve_studio(load_studio(notebook_path))

    assert resolved.runtime_cell_bindings(None)["result"] == {
        "kind": "id",
        "value": bound.cell.runtime_id,
    }
    assert set(resolved.view("dashboard").value_bindings) == {"doubled"}
    assert set(resolved.view("executive").value_bindings) == {"x"}
    assert set(_template_selectors(notebook_path) or ()) == {"doubled", "x"}


def test_kernel_selectors_ignore_an_invalid_unselected_view(
    notebook_path: Path,
) -> None:
    ensure_view(notebook_path)
    studio = load_studio(notebook_path)
    _shell(studio, "dashboard", '<span mo-value="doubled"></span>')
    ensure_view(notebook_path, "draft")
    studio = load_studio(notebook_path)
    _shell(studio, "draft", '<span mo-value="doubled + 1"></span>')

    assert _template_selectors(notebook_path) == ("doubled",)


@pytest.mark.parametrize(
    ("template", "message"),
    [
        ("<html><head></head><body></body></html>", "expected one element"),
        (
            '<html><head><body><main id="app-shell"></main>',
            "expected one <head>",
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
            '<main id="app-shell"><span mo-value="doubled + 1"></span></main>',
            "Invalid mo-value reference",
        ),
        (
            '<main id="app-shell"><span mo-value="missing"></span></main>',
            "undefined notebook variables",
        ),
        (
            '<main id="app-shell"><marimo-cell name="missing"></marimo-cell></main>',
            "unbound cell aliases",
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
    ensure_view(notebook_path)
    studio = load_studio(notebook_path)
    if not template.startswith("<html"):
        template = f"<html><head></head><body>{template}</body></html>"
    studio.views["dashboard"].template.write_text(template, encoding="utf-8")

    with pytest.raises(ConfigurationError, match=message):
        resolve_studio(load_studio(notebook_path))


@pytest.mark.parametrize("name", ["lsp", "mcp", "sse", "studio"])
def test_view_names_cannot_claim_application_routes(
    notebook_path: Path,
    name: str,
) -> None:
    ensure_view(notebook_path)
    with pytest.raises(ConfigurationError, match=f"{name!r} is reserved"):
        ensure_view(notebook_path, name)


def test_changed_binding_has_one_recovery_path(notebook_path: Path) -> None:
    ensure_view(notebook_path)
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

    with pytest.raises(BindingError, match="bind the alias again with --overwrite"):
        resolve_studio(load_studio(notebook_path))


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
    ensure_view(notebook)
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

    with pytest.raises(BindingError, match="became ambiguous"):
        resolve_studio(load_studio(notebook))


def test_runtime_check_scopes_values_to_the_selected_view(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_view(notebook_path)
    studio = load_studio(notebook_path)
    bound = bind_cell(studio, "result", 1)
    ensure_view(notebook_path, "executive")
    studio = load_studio(notebook_path)
    _shell(
        studio,
        "dashboard",
        '<marimo-cell name="result"></marimo-cell>'
        '<span mo-value="doubled.missing"></span>',
    )
    _shell(studio, "executive", '<span mo-value="x"></span>')
    captured: dict[str, object] = {}

    async def probe(*_: object, **kwargs: object) -> RuntimeProbe:
        captured.update(kwargs)
        return RuntimeProbe(
            cells={
                bound.cell.runtime_id: RuntimeCell(
                    status="idle",
                    outputs=(),
                    errors=(),
                )
            },
            values=ValueReadResult(
                values={},
                errors={
                    "doubled.missing": ValueReadError(
                        "value-path-unavailable",
                        "Missing key",
                    )
                },
            ),
        )

    monkeypatch.setattr(checks_module, "probe_runtime", probe)
    results = asyncio.run(
        check_runtime_studio(load_studio(notebook_path), view_name="dashboard")
    )

    assert captured["variables"] == ("doubled.missing",)
    assert {result.name for result in results if result.status == "fail"} == {
        "runtime-cell:result",
        "runtime-value:doubled.missing",
    }


def test_runtime_check_includes_cells_loaded_through_htmx(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_view(notebook_path)
    studio = load_studio(notebook_path)
    bound = bind_cell(studio, "result", 1)
    _shell(
        studio,
        "dashboard",
        '<button hx-get="./_marimo-studio/views/dashboard/cells/result">'
        "Load result"
        "</button>",
    )
    captured: dict[str, object] = {}

    async def probe(*_: object, **kwargs: object) -> RuntimeProbe:
        captured.update(kwargs)
        return RuntimeProbe(
            cells={
                bound.cell.runtime_id: RuntimeCell(
                    status="idle",
                    outputs=(),
                    errors=(),
                )
            },
            values=ValueReadResult(values={}, errors={}),
        )

    monkeypatch.setattr(checks_module, "probe_runtime", probe)
    results = asyncio.run(
        check_runtime_studio(load_studio(notebook_path), view_name="dashboard")
    )

    assert captured["cell_ids"] == (bound.cell.runtime_id,)
    assert [result.name for result in results] == ["runtime-cell:result"]
    assert results[0].status == "fail"


def test_selected_view_check_isolated_from_other_templates(
    notebook_path: Path,
) -> None:
    ensure_view(notebook_path)
    studio = load_studio(notebook_path)
    ensure_view(notebook_path, "executive")
    studio = load_studio(notebook_path)
    _shell(studio, "dashboard", '<span mo-value="missing"></span>')

    selected = check_studio(load_studio(notebook_path), view_name="executive")
    all_views = check_studio(load_studio(notebook_path))

    assert all(result.status == "pass" for result in selected)
    assert any(result.status == "fail" for result in all_views)


def test_mutable_symlink_rejects_the_setup_before_notebook_changes(
    notebook_path: Path,
    tmp_path: Path,
) -> None:
    original = notebook_path.read_bytes()
    marimo_dir = notebook_path.parent / "__marimo__"
    external = tmp_path / "external"
    external.mkdir()
    marimo_dir.symlink_to(external, target_is_directory=True)

    with pytest.raises(ConfigurationError, match="symlink"):
        ensure_view(notebook_path)

    assert notebook_path.read_bytes() == original
    assert list(external.iterdir()) == []
