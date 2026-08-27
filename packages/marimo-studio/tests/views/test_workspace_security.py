from __future__ import annotations

from pathlib import Path

import pytest

from marimo_studio._views.api import prepare_view
from marimo_studio.errors import (
    ConfigurationError,
)


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
        prepare_view(notebook_path)

    assert notebook_path.read_bytes() == original
    assert list(external.iterdir()) == []
