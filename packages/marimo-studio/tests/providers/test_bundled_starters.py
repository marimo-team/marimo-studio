from __future__ import annotations

import importlib
import sys
from pathlib import Path, PurePosixPath

import marimo
import pytest

from marimo_studio import inspect_notebook
from marimo_studio._views.starter_context import starter_context
from marimo_studio.view_providers import ProviderStarter
from marimo_studio.view_providers._bundled._starters import (
    BundledStarter,
    StarterRendering,
    create_starter,
    starter_catalog,
    starter_cells,
)
from marimo_studio.view_providers._bundled.deno_react import provider as react_provider
from marimo_studio.view_providers._bundled.vanilla import provider as vanilla_provider

from ..provider_test_support import provider_starter_context


def _fixture_package(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    files: dict[str, str | bytes],
) -> str:
    package = tmp_path / "bundled_starter_fixture"
    package.mkdir()
    package.joinpath("__init__.py").write_text("", encoding="utf-8")
    for relative, content in files.items():
        path = package / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    for module in tuple(sys.modules):
        if module == package.name or module.startswith(f"{package.name}."):
            sys.modules.pop(module)
    importlib.invalidate_caches()
    return f"{package.name}.default"


def _starter() -> ProviderStarter:
    return ProviderStarter(
        key="default",
        title="Fixture",
        summary="A packaged starter fixture.",
        documents=(PurePosixPath("index.html"),),
    )


def test_bundled_starter_reads_resources_from_its_leaf_package(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = _fixture_package(
        tmp_path,
        monkeypatch,
        {
            "other/files/ignored.txt": "ignored",
            "default/__init__.py": "",
            "default/files/index.html": "default",
        },
    )
    info = _starter()
    starter = BundledStarter(
        info=info,
        package=package,
        render=lambda _context: StarterRendering({}, ()),
    )

    plan = create_starter(
        starter_catalog(starter),
        info,
        provider_starter_context(tmp_path),
    )

    assert plan.files == {PurePosixPath("index.html"): b"default"}


def test_bundled_starter_preserves_binary_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image = b"\x89PNG\r\n\x1a\n\xff"
    package = _fixture_package(
        tmp_path,
        monkeypatch,
        {
            "default/__init__.py": "",
            "default/files/index.html": '<main id="app-shell"></main>',
            "default/files/public/mark.png": image,
        },
    )
    info = _starter()
    starter = BundledStarter(
        info=info,
        package=package,
        render=lambda _context: StarterRendering({}, ()),
    )

    plan = create_starter(
        starter_catalog(starter),
        info,
        provider_starter_context(tmp_path),
    )

    assert plan.files[PurePosixPath("public/mark.png")] == image


def test_bundled_starter_matches_replacement_line_endings_to_its_resource(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = _fixture_package(
        tmp_path,
        monkeypatch,
        {
            "default/__init__.py": "",
            "default/files/index.html": b"<main>\r\n__BODY__\r\n</main>\r\n",
        },
    )
    info = _starter()
    starter = BundledStarter(
        info=info,
        package=package,
        render=lambda _context: StarterRendering(
            {"__BODY__": "first\nsecond"},
            (),
        ),
    )

    plan = create_starter(
        starter_catalog(starter),
        info,
        provider_starter_context(tmp_path),
    )

    assert plan.files[PurePosixPath("index.html")] == (
        b"<main>\r\nfirst\r\nsecond\r\n</main>\r\n"
    )


def test_reveal_starter_uses_markdown_title_and_notebook_cells(
    tmp_path: Path,
) -> None:
    notebook = tmp_path / "research_notes.py"
    notebook.write_text(
        f'''\
import marimo

__generated_with = "{marimo.__version__}"
app = marimo.App()

@app.cell
def _():
    import marimo as mo
    return (mo,)

@app.cell
def introduction(mo):
    mo.md(r"""
    ````
    # Fenced example
    ```
    ````

    # **Evidence** C#

    Current results.
    """)
    return

if __name__ == "__main__":
    app.run()
''',
        encoding="utf-8",
    )
    context = starter_context(
        inspect_notebook(notebook, include_code=True),
        None,
        "slides",
    )
    starter = next(item for item in react_provider.starters() if item.key == "reveal")

    plan = react_provider.create(starter, context)

    source = plan.files[PurePosixPath("src/App.tsx")].decode()
    assert 'const NOTEBOOK_TITLE = "Evidence C#";' in source
    assert [target.target for target in plan.cell_targets] == ["introduction"]
    assert "<marimo-cell name={target} />" in source


def test_starter_cells_exclude_the_transitive_disabled_closure(
    tmp_path: Path,
) -> None:
    notebook = tmp_path / "disabled.py"
    notebook.write_text(
        f'''\
import marimo

__generated_with = "{marimo.__version__}"
app = marimo.App()

@app.cell(disabled=True)
def producer():
    value = 1
    value
    return (value,)

@app.cell
def dependent(value):
    doubled = value * 2
    doubled
    return (doubled,)

@app.cell
def independent():
    "ready"
    return

if __name__ == "__main__":
    app.run()
''',
        encoding="utf-8",
    )
    context = starter_context(
        inspect_notebook(notebook, include_code=True),
        None,
        "dashboard",
    )

    assert [target.target for _cell, target in starter_cells(context)] == [
        "independent"
    ]


@pytest.mark.parametrize(
    ("filename", "app", "label"),
    (
        (
            "example.py",
            'marimo.App(app_title="Quadratic Program")',
            "Quadratic Program",
        ),
        ("research-notes.py", "marimo.App()", "Research Notes"),
    ),
    ids=("app-title", "filename"),
)
def test_vanilla_starter_labels_the_page_with_the_notebook_title(
    tmp_path: Path,
    filename: str,
    app: str,
    label: str,
) -> None:
    notebook = tmp_path / filename
    notebook.write_text(
        f"""\
import marimo

__generated_with = "{marimo.__version__}"
app = {app}

@app.cell
def _():
    import marimo as mo
    return (mo,)

if __name__ == "__main__":
    app.run()
""",
        encoding="utf-8",
    )
    context = starter_context(
        inspect_notebook(notebook, include_code=True),
        None,
        "dashboard",
    )
    starter = next(
        item for item in vanilla_provider.starters() if item.key == "default"
    )

    page = (
        vanilla_provider.create(starter, context)
        .files[PurePosixPath("index.html")]
        .decode()
    )

    assert f"<title>{label} · Dashboard</title>" in page
