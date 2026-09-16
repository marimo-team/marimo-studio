from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

import marimo_studio._workspace.config as workspace_config
from marimo_studio._views.api import prepare_view
from marimo_studio._workspace import load_studio
from marimo_studio._workspace.config_snapshot import snapshot_workspace_config
from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio.errors import ConfigurationError, WorkspaceGenerationConflictError


def _project_workspace(notebook: Path) -> StudioWorkspace:
    pyproject = notebook.parent / "pyproject.toml"
    pyproject.write_text(
        f'''\
[tool.marimo-studio]
notebook = "{notebook.name}"
default = "dashboard"
''',
        encoding="utf-8",
    )
    prepare_view(notebook)
    return load_studio(pyproject)


def test_inline_config_snapshot_deduplicates_the_notebook_identity(
    notebook_path: Path,
) -> None:
    prepare_view(notebook_path)
    studio = load_studio(notebook_path)

    snapshot = snapshot_workspace_config(
        studio,
        reload_studio=load_studio,
        include_notebook=True,
    )

    assert snapshot.source == notebook_path.read_bytes().decode("utf-8")
    assert snapshot.notebook_identity == snapshot.config_identity
    assert snapshot.expected_identities == {
        notebook_path: snapshot.config_identity,
    }


def test_project_config_snapshot_selects_its_read_set(
    notebook_path: Path,
) -> None:
    studio = _project_workspace(notebook_path)

    config_only = snapshot_workspace_config(studio, reload_studio=load_studio)
    with_notebook = snapshot_workspace_config(
        studio,
        reload_studio=load_studio,
        include_notebook=True,
    )

    assert config_only.notebook_identity is None
    assert config_only.expected_identities == {
        studio.config_path: config_only.config_identity,
    }
    assert with_notebook.notebook_identity is not None
    assert with_notebook.expected_identities == {
        studio.config_path: with_notebook.config_identity,
        notebook_path: with_notebook.notebook_identity,
    }


def test_config_snapshot_rejects_non_utf8_source(notebook_path: Path) -> None:
    studio = _project_workspace(notebook_path)
    studio.config_path.write_bytes(b"\xff")

    with pytest.raises(ConfigurationError, match="not UTF-8"):
        snapshot_workspace_config(studio, reload_studio=load_studio)


@pytest.mark.parametrize("missing_read", [1, 2])
def test_configuration_load_reports_a_replacement_conflict(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    missing_read: int,
) -> None:
    prepare_view(notebook_path)
    original = workspace_config.read_file_snapshot_with_identity
    reads = 0
    claimed = notebook_path.with_suffix(".rollback")

    def read_snapshot(path: Path, *, root: Path):
        nonlocal reads
        reads += 1
        if reads == missing_read:
            notebook_path.rename(claimed)
        return original(path, root=root)

    monkeypatch.setattr(
        workspace_config, "read_file_snapshot_with_identity", read_snapshot
    )
    try:
        with pytest.raises(WorkspaceGenerationConflictError):
            workspace_config.load_studio_definition(notebook_path)
    finally:
        if claimed.exists():
            claimed.rename(notebook_path)

    assert load_studio(notebook_path).default_view == "dashboard"


def test_config_snapshot_rejects_a_config_edit_during_reload(
    notebook_path: Path,
) -> None:
    studio = _project_workspace(notebook_path)

    def edit_then_reload(path: Path) -> StudioWorkspace:
        path.write_text(
            path.read_text(encoding="utf-8") + "# concurrent edit\n",
            encoding="utf-8",
        )
        return load_studio(path)

    with pytest.raises(ConfigurationError, match="snapshot was captured"):
        snapshot_workspace_config(studio, reload_studio=edit_then_reload)


def test_config_snapshot_rejects_source_aba_during_reload(
    notebook_path: Path,
) -> None:
    studio = _project_workspace(notebook_path)
    prepare_view(notebook_path, "other")
    studio = load_studio(studio.config_path)
    original = studio.config_path.read_text(encoding="utf-8")
    transient = original.replace(
        'default = "dashboard"',
        'default = "other"',
    )

    def aba_reload(path: Path) -> StudioWorkspace:
        path.write_text(transient, encoding="utf-8")
        current = load_studio(path)
        path.write_text(original, encoding="utf-8")
        return current

    with pytest.raises(ConfigurationError, match="snapshot was captured"):
        snapshot_workspace_config(studio, reload_studio=aba_reload)


def test_config_snapshot_rejects_a_requested_notebook_edit_during_reload(
    notebook_path: Path,
) -> None:
    studio = _project_workspace(notebook_path)

    def edit_then_reload(path: Path) -> StudioWorkspace:
        notebook_path.write_text(
            notebook_path.read_text(encoding="utf-8") + "# concurrent edit\n",
            encoding="utf-8",
        )
        return load_studio(path)

    with pytest.raises(ConfigurationError, match="snapshot was captured"):
        snapshot_workspace_config(
            studio,
            reload_studio=edit_then_reload,
            include_notebook=True,
        )


def test_config_snapshot_rejects_a_reloaded_owner_change(
    notebook_path: Path,
) -> None:
    prepare_view(notebook_path)
    studio = load_studio(notebook_path)

    with pytest.raises(ConfigurationError, match="snapshot was captured"):
        snapshot_workspace_config(
            studio,
            reload_studio=lambda _path: replace(
                studio,
                view_root=studio.view_root.with_name("other"),
            ),
        )
