"""Protect browser notebook dependency ownership."""

from __future__ import annotations

from pathlib import Path

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
