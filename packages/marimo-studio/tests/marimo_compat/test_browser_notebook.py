"""Protect browser notebook dependency ownership."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import marimo_studio._compat.browser_notebook as browser_notebook
from marimo_studio._compat.browser_notebook import browser_notebook_source
from marimo_studio._workspace.metadata import (
    browser_notebook_metadata_source,
    configured_notebook_source,
    read_notebook_metadata,
)


def _source(dependencies: list[str], body: str = "import marimo\n") -> str:
    rendered = ", ".join(repr(item) for item in dependencies)
    return f"# /// script\n# dependencies = [{rendered}]\n# ///\n\n{body}"


def _metadata(source: str, notebook: Path):
    notebook.write_text(source, encoding="utf-8")
    document = read_notebook_metadata(notebook)
    assert document is not None
    return document


def test_browser_metadata_source_removes_runtime_specific_configuration(
    tmp_path: Path,
) -> None:
    notebook = tmp_path / "analysis.py"
    source = """# /// script
# requires-python = ">=3.12"
# dependencies = ["marimo-studio==0.1.0", "example-provider==1.2.3", "polars"]
#
# [tool.marimo-studio]
# default = "dashboard"
# provider_dependencies = ["example-provider==1.2.3"]
#
# [tool.uv.sources]
# marimo-studio = { path = "../marimo-studio" }
#
# [tool.application]
# theme = "dark"
# ///

import marimo
"""

    projected_metadata = _metadata(
        browser_notebook_metadata_source(
            notebook,
            source,
            imported_distributions=(),
        ),
        notebook,
    )

    assert list(projected_metadata["dependencies"]) == ["polars"]
    assert projected_metadata["requires-python"] == ">=3.12"
    assert set(projected_metadata["tool"]) == {"application"}
    assert projected_metadata["tool"]["application"]["theme"] == "dark"


def test_browser_notebook_removes_dependencies_added_for_providers(
    tmp_path: Path,
) -> None:
    notebook = tmp_path / "analysis.py"
    source = _source(["polars==1.0.0"])
    configured = configured_notebook_source(
        notebook,
        "dashboard",
        ["marimo-studio[deno]", "example-provider==1.2.3"],
        source=source,
    )

    configured_metadata = _metadata(configured, notebook)
    projected_metadata = _metadata(
        browser_notebook_source(notebook, configured),
        notebook,
    )

    assert list(
        configured_metadata["tool"]["marimo-studio"]["provider_dependencies"]
    ) == ["example-provider==1.2.3"]
    assert [str(item) for item in projected_metadata["dependencies"]] == [
        "polars==1.0.0"
    ]


def test_browser_notebook_preserves_preexisting_provider_distribution_requirement(
    tmp_path: Path,
) -> None:
    notebook = tmp_path / "analysis.py"
    source = _source(
        ["example-provider>=1", "runtime-package==4.5.6"],
        'import marimo\nruntime = __import__("example_runtime")\n',
    )
    configured = configured_notebook_source(
        notebook,
        "dashboard",
        ["example-provider==1.2.3"],
        source=source,
    )

    configured_metadata = _metadata(configured, notebook)
    projected_metadata = _metadata(
        browser_notebook_source(notebook, configured),
        notebook,
    )

    assert "provider_dependencies" not in configured_metadata["tool"]["marimo-studio"]
    assert [str(item) for item in projected_metadata["dependencies"]] == [
        "example-provider>=1",
        "runtime-package==4.5.6",
    ]


@pytest.mark.parametrize(
    "dependency",
    (
        "example-provider[wasm]>=1",
        "example-provider[wasm] @ file:///tmp/example-provider",
    ),
)
def test_browser_notebook_preserves_provider_runtime_requirement_shape(
    tmp_path: Path,
    dependency: str,
) -> None:
    notebook = tmp_path / "analysis.py"
    configured = configured_notebook_source(
        notebook,
        "dashboard",
        ["example-provider==1.2.3"],
        source=_source([dependency]),
    )

    configured_metadata = _metadata(configured, notebook)
    projected_metadata = _metadata(
        browser_notebook_source(notebook, configured),
        notebook,
    )

    assert dependency in [str(item) for item in configured_metadata["dependencies"]]
    assert dependency in [str(item) for item in projected_metadata["dependencies"]]
    assert "provider_dependencies" not in configured_metadata["tool"]["marimo-studio"]


def test_browser_notebook_releases_ownership_after_dependency_edit(
    tmp_path: Path,
) -> None:
    notebook = tmp_path / "analysis.py"
    configured = configured_notebook_source(
        notebook,
        "dashboard",
        ["example-provider==1.2.3"],
        source=_source([]),
    )
    claimed = configured.replace(
        '"example-provider==1.2.3"',
        '"example-provider>=1"',
        1,
    )

    projected_metadata = _metadata(
        browser_notebook_source(notebook, claimed),
        notebook,
    )
    reconfigured_metadata = _metadata(
        configured_notebook_source(
            notebook,
            "dashboard",
            ["example-provider==1.2.3"],
            source=claimed,
        ),
        notebook,
    )

    assert [str(item) for item in projected_metadata["dependencies"]] == [
        "example-provider>=1"
    ]
    assert "provider_dependencies" not in reconfigured_metadata["tool"]["marimo-studio"]


def test_browser_notebook_preserves_provider_distribution_after_runtime_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notebook = tmp_path / "analysis.py"
    configured = configured_notebook_source(
        notebook,
        "dashboard",
        ["example-provider==1.2.3"],
        source=_source([]),
    )
    configured += "\nimport example_runtime\n"
    monkeypatch.setattr(
        browser_notebook,
        "packages_distributions",
        lambda: {"example_runtime": ["example-provider"]},
    )

    projected_metadata = _metadata(
        browser_notebook_source(notebook, configured),
        notebook,
    )

    assert [str(item) for item in projected_metadata["dependencies"]] == [
        "example-provider==1.2.3"
    ]


def test_browser_notebook_removes_equivalent_provider_requirement_spelling(
    tmp_path: Path,
) -> None:
    notebook = tmp_path / "analysis.py"
    configured = configured_notebook_source(
        notebook,
        "dashboard",
        ["example-provider==1.0"],
        source=_source([]),
    )
    normalized = configured.replace(
        '"example-provider==1.0"',
        '"example-provider==1.0.0"',
        1,
    )

    projected_metadata = _metadata(
        browser_notebook_source(notebook, normalized),
        notebook,
    )

    assert list(projected_metadata["dependencies"]) == []


@pytest.mark.parametrize("separator", ["\x0c", "\u2028", "\x85"])
def test_browser_notebook_places_its_bridge_after_cells_with_line_separators(
    tmp_path: Path,
    separator: str,
) -> None:
    import ast

    source = (
        "import marimo\n\n"
        '__generated_with = "0.25.1"\n'
        "app = marimo.App()\n\n\n"
        "@app.cell\n"
        "def _():\n"
        f'    text = "a{separator * 4}b"\n'
        "    return (text,)\n\n\n"
        "@app.cell\n"
        "def _(text):\n"
        "    text\n"
        "    return\n\n\n"
        'if __name__ == "__main__":\n'
        "    app.run()\n"
    )

    browser = browser_notebook_source(tmp_path / "notebook.py", source)

    ast.parse(browser)
    bridge = browser.index("def __marimo_studio_values():")
    assert browser.index("def _(text):") < bridge < browser.index("if __name__")


def test_generated_browser_bridge_and_kernel_render_the_same_output_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from contextlib import nullcontext
    from types import SimpleNamespace

    from marimo._types.ids import CellId_t

    from marimo_studio._compat.browser_notebook import _value_bridge
    from marimo_studio._compat.kernel_values.models import OUTPUT_OWNER_PREFIX
    from marimo_studio._compat.kernel_values.outputs import KernelOutputRenderer

    from .values_test_support import _native_output_context, _selectors

    class _App:
        function: Any

        def cell(self, *_args: object, **_kwargs: object):
            def register(function: object) -> object:
                self.function = function
                return function

            return register

    app = _App()
    exec(_value_bridge(), {"app": app})
    context = _native_output_context()
    values = {"summary": "ready"}
    monkeypatch.setattr(type(context), "globals", property(lambda _self: values))
    context._kernel = SimpleNamespace(lock_globals=nullcontext)
    monkeypatch.setattr(
        "marimo._messaging.notification_utils.broadcast_notification",
        lambda _: None,
    )
    renderer = KernelOutputRenderer(context)
    site = {
        "id": "site-summary",
        "kind": "output",
        "source": {"path": "index.html", "line": 1, "column": 1},
        "targets": ["summary"],
        "accept": [],
        "size": None,
        "render": None,
    }
    request = {
        "siteId": "site-summary",
        "instanceId": "summary-host",
        "target": "summary",
    }
    try:
        with context.install():
            with context.with_cell_id(CellId_t("bridge")):
                app.function()
            functions = context.function_registry.namespaces[
                "_marimo_studio_wasm"
            ].functions
            functions["configure_projections"](
                {
                    "revision": "revision-1",
                    "generation": 0,
                    "sites": [site],
                    "variables": ["summary"],
                }
            )
            rendered = functions["render_values"](
                {
                    "revision": "revision-1",
                    "projections": [request],
                    "active_projections": [request],
                    "consumer_id": "preview-a",
                }
            )
            kernel = renderer.render(
                values,
                _selectors("summary"),
                ("summary",),
                {},
                consumer_id="preview-a",
                max_output_bytes=10_000,
            )
            owner = kernel.outputs["summary"].owner_cell_id
            assert rendered["errors"] == {}
            assert rendered["outputs"]["summary"]["ownerCellId"] == owner
            assert str(owner).startswith(OUTPUT_OWNER_PREFIX)
    finally:
        with context.install():
            renderer.close()
            context.cell_lifecycle_registry.dispose(CellId_t("bridge"), deletion=False)
        context.virtual_file_registry.shutdown()


@pytest.mark.parametrize(
    ("kind", "accept", "render", "valid"),
    (
        ("output", ["image/png"], None, True),
        ("cell", ["image/png"], None, False),
        ("value", ["application/json"], None, False),
        ("value", ["application/json"], "main.typ", True),
        ("cell", ["image/png"], "main.typ", True),
        ("cell", [], "main.typ", False),
    ),
    ids=(
        "page-output-image",
        "page-cell-media",
        "page-value-json",
        "render-value-json",
        "render-cell-image",
        "render-cell-without-media",
    ),
)
def test_generated_browser_bridge_admits_only_the_accept_lists_studio_publishes(
    kind: str,
    accept: list[str],
    render: str | None,
    valid: bool,
) -> None:
    from marimo._types.ids import CellId_t

    from marimo_studio._compat.browser_notebook import _value_bridge

    from .values_test_support import _native_output_context

    class _App:
        function: Any

        def cell(self, *_args: object, **_kwargs: object):
            def register(function: object) -> object:
                self.function = function
                return function

            return register

    app = _App()
    exec(_value_bridge(), {"app": app})
    context = _native_output_context()
    site = {
        "id": "site-summary",
        "kind": kind,
        "source": {"path": "index.html", "line": 1, "column": 1},
        "targets": ["summary"],
        "accept": accept,
        "size": None,
        "render": render,
    }
    try:
        with context.install():
            with context.with_cell_id(CellId_t("bridge")):
                app.function()
            configure = context.function_registry.namespaces[
                "_marimo_studio_wasm"
            ].functions["configure_projections"]
            arguments = {
                "revision": "revision-1",
                "generation": 0,
                "sites": [site],
                "variables": ["summary"],
            }
            if valid:
                configure(arguments)
            else:
                with pytest.raises(ValueError, match="A projection site is invalid"):
                    configure(arguments)
    finally:
        with context.install():
            context.cell_lifecycle_registry.dispose(CellId_t("bridge"), deletion=False)
        context.virtual_file_registry.shutdown()
