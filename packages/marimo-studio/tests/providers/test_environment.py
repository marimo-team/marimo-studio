"""Protect provider dependencies needed to reopen Studio views."""

from __future__ import annotations

from pathlib import Path

import pytest

from marimo_studio._views.api import prepare_view
from marimo_studio._views.remove import delete_view
from marimo_studio._workspace import load_studio
from marimo_studio._workspace.metadata import read_notebook_metadata
from marimo_studio.errors import ConfigurationError
from marimo_studio.view_providers._host.package_policy import (
    BUNDLED_PROVIDER_REQUIREMENTS,
)
from marimo_studio.view_providers._host.registry import ProviderRegistry

from ..provider_test_support import (
    ProviderStub,
    candidate,
    install_registry,
)


def test_setup_normalizes_studio_constraints_and_preserves_notebook_body(
    notebook_path: Path,
) -> None:
    body = notebook_path.read_text(encoding="utf-8")
    notebook_path.write_text(
        """# /// script
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

    prepare_view(notebook_path, "finance")
    document = read_notebook_metadata(notebook_path)

    assert document is not None
    assert document["requires-python"] == ">=3.12,<3.15"
    assert document["tool"]["marimo"]["runtime"]["auto_instantiate"] is True
    assert document["tool"]["marimo-studio"]["default"] == "finance"
    assert [
        str(value)
        for value in document["dependencies"]
        if "marimo-studio" in str(value)
    ] == ["marimo-studio==0.1.0"]
    assert notebook_path.read_text(encoding="utf-8").endswith(body)


def test_view_deletion_keeps_dependencies_and_updates_the_default(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    react = ProviderStub("marimo-studio/react", "react")
    install_registry(
        monkeypatch,
        ProviderRegistry(
            (candidate("react", react, distribution="marimo-studio"),),
            BUNDLED_PROVIDER_REQUIREMENTS,
        ),
    )
    prepare_view(
        notebook_path,
        "dashboard",
        starter="marimo-studio/react:react",
    )
    prepare_view(
        notebook_path,
        "report",
        starter="marimo-studio/react:react",
    )
    studio = load_studio(notebook_path)
    before = read_notebook_metadata(notebook_path)
    assert before is not None
    assert list(before["dependencies"]) == ["marimo-studio[deno]==0.1.0"]

    delete_view(studio, "dashboard")

    after = read_notebook_metadata(notebook_path)
    assert after is not None
    assert after["tool"]["marimo-studio"]["default"] == "report"
    assert after["dependencies"] == before["dependencies"]


def test_setup_tightens_the_notebook_python_requirement(
    notebook_path: Path,
) -> None:
    body = notebook_path.read_text(encoding="utf-8")
    notebook_path.write_text(
        """# /// script
# requires-python = ">=3.9,<3.13"
# dependencies = []
# ///

"""
        + body,
        encoding="utf-8",
    )

    prepare_view(notebook_path)

    document = read_notebook_metadata(notebook_path)
    assert document is not None
    assert document["requires-python"] == ">=3.10,<3.13"


def test_setup_rejects_disjoint_python_requirements_before_mutation(
    notebook_path: Path,
) -> None:
    notebook_path.write_text(
        notebook_path.read_text(encoding="utf-8").replace(
            "import marimo",
            '# /// script\n# requires-python = "<3.10"\n'
            "# dependencies = []\n# ///\n\nimport marimo",
        ),
        encoding="utf-8",
    )
    original = notebook_path.read_bytes()

    with pytest.raises(ConfigurationError, match="do not overlap"):
        prepare_view(notebook_path)

    assert notebook_path.read_bytes() == original
    assert not (notebook_path.parent / "__marimo__").exists()
