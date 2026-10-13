from __future__ import annotations

import sys
from pathlib import Path

import pytest
from marimo._utils.paths import notebook_output_dir

from marimo_studio._workspace.locations import notebook_output_directory


@pytest.mark.supported_python
@pytest.mark.parametrize("prefix", (None, "cache-prefix"))
def test_view_state_follows_the_marimo_output_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    prefix: str | None,
) -> None:
    notebook = (tmp_path / "project" / "notebooks" / "analysis.py").resolve()
    monkeypatch.setattr(
        sys, "pycache_prefix", str(tmp_path / prefix) if prefix else None
    )

    assert notebook_output_directory(notebook) == notebook_output_dir(notebook)


@pytest.mark.skipif(
    sys.platform == "win32", reason="symlink creation needs elevated Windows access"
)
def test_view_state_mirrors_the_resolved_notebook_folder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    folder = tmp_path / "folder"
    folder.mkdir()
    link = tmp_path / "link"
    link.symlink_to(folder, target_is_directory=True)
    monkeypatch.setattr(sys, "pycache_prefix", str(tmp_path / "prefix"))

    assert notebook_output_directory(link / "analysis.py") == notebook_output_dir(
        (folder / "analysis.py").resolve()
    )
