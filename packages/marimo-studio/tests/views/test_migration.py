"""Exercise authored workspace migration."""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

import marimo_studio._views.migrate as migrate_module
from marimo_studio._cli import cli
from marimo_studio._views.api import migrate_workspace
from marimo_studio._views.build import build_view_project
from marimo_studio._workspace import load_studio
from marimo_studio._workspace.config import load_studio_definition
from marimo_studio.errors import ViewProjectError

_FIXTURE = Path(__file__).parents[1] / "fixtures" / "v0_0_6_workspace"


def _copy_workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    shutil.copytree(_FIXTURE, root)
    return root / "analysis.py"


def _authored_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_migration_preserves_authored_files_and_builds_the_converted_view(
    tmp_path: Path,
) -> None:
    notebook = _copy_workspace(tmp_path)
    original = _authored_hashes(notebook.parent)

    preview = migrate_workspace(notebook, dry_run=True)

    assert preview.views == ("dashboard",)
    assert _authored_hashes(notebook.parent) == original

    migrated = migrate_workspace(notebook)
    retained = {
        path: digest
        for path, digest in _authored_hashes(notebook.parent).items()
        if path in original
    }
    repeated = migrate_workspace(notebook)
    studio = load_studio(notebook)
    publication = asyncio.run(build_view_project(studio.view("dashboard")))

    assert retained == original
    assert migrated.views == ("dashboard",)
    assert {path.name for path in migrated.created} == {".gitignore", "view.toml"}
    assert migrated.updated == ()
    assert studio.view("dashboard").provider == "marimo-studio/vanilla"
    assert publication.artifact_id.startswith("sha256:")
    assert repeated.views == ()
    assert repeated.created == ()
    assert repeated.updated == ()


def test_migration_reports_an_existing_ignore_file_as_updated(tmp_path: Path) -> None:
    notebook = _copy_workspace(tmp_path)
    ignore = load_studio_definition(notebook).view_root / ".gitignore"
    ignore.write_text("local-entry\n", encoding="utf-8")

    preview = migrate_workspace(notebook, dry_run=True)
    migrated = migrate_workspace(notebook)

    assert {path.name for path in preview.created} == {"view.toml"}
    assert preview.updated == (ignore,)
    assert {path.name for path in migrated.created} == {"view.toml"}
    assert migrated.updated == (ignore,)


def test_migration_rejects_a_legacy_view_that_fetches_local_files(
    tmp_path: Path,
) -> None:
    notebook = _copy_workspace(tmp_path)
    view = load_studio_definition(notebook).view_root / "dashboard"
    document = view / "index.html"
    document.write_text(
        document.read_text(encoding="utf-8").replace(
            "</head>",
            '<link rel="stylesheet" href="app.css" /></head>',
        ),
        encoding="utf-8",
    )
    with pytest.raises(ViewProjectError, match="provider for multi-file projects"):
        migrate_workspace(notebook, dry_run=True)
    with pytest.raises(ViewProjectError, match="provider for multi-file projects"):
        migrate_workspace(notebook)

    assert not (view / "view.toml").exists()


def test_migration_rejects_additional_authored_files(tmp_path: Path) -> None:
    notebook = _copy_workspace(tmp_path)
    view = load_studio_definition(notebook).view_root / "dashboard"
    (view / "notes.txt").write_text("authored notes\n", encoding="utf-8")

    with pytest.raises(ViewProjectError, match="Inline or remove the sibling file"):
        migrate_workspace(notebook, dry_run=True)

    assert not (view / "view.toml").exists()


def test_migration_ignores_generated_control_files(tmp_path: Path) -> None:
    notebook = _copy_workspace(tmp_path)
    view = load_studio_definition(notebook).view_root / "dashboard"
    generated = view / ".artifacts" / "cache" / "state.bin"
    generated.parent.mkdir(parents=True)
    generated.write_bytes(b"generated")

    preview = migrate_workspace(notebook, dry_run=True)

    assert preview.views == ("dashboard",)


def test_migration_reports_malformed_resource_urls(tmp_path: Path) -> None:
    notebook = _copy_workspace(tmp_path)
    view = load_studio_definition(notebook).view_root / "dashboard"
    document = view / "index.html"
    document.write_text(
        document.read_text(encoding="utf-8").replace(
            "</head>",
            '<style>body { background: url("http://[") }</style></head>',
        ),
        encoding="utf-8",
    )

    with pytest.raises(ViewProjectError, match="Invalid resource URL") as error:
        migrate_workspace(notebook, dry_run=True)

    assert error.value.source == document
    assert not (view / "view.toml").exists()


def test_migration_reports_a_non_utf8_entry_document(tmp_path: Path) -> None:
    notebook = _copy_workspace(tmp_path)
    document = load_studio_definition(notebook).view_root / "dashboard" / "index.html"
    document.write_bytes(b"\xff\xfe")

    with pytest.raises(ViewProjectError, match="must be UTF-8") as error:
        migrate_workspace(notebook, dry_run=True)

    assert error.value.source == document


def test_migration_reports_an_entry_document_read_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notebook = _copy_workspace(tmp_path)
    document = load_studio_definition(notebook).view_root / "dashboard" / "index.html"
    read_text = migrate_module.read_text

    def fail_entry_read(path: Path) -> str:
        if path == document:
            raise PermissionError("unavailable")
        return read_text(path)

    monkeypatch.setattr(migrate_module, "read_text", fail_entry_read)

    with pytest.raises(ViewProjectError, match="is unavailable") as error:
        migrate_workspace(notebook, dry_run=True)

    assert error.value.source == document


def test_view_migrate_command_reports_the_converted_workspace(tmp_path: Path) -> None:
    notebook = _copy_workspace(tmp_path)
    ignore = load_studio_definition(notebook).view_root / ".gitignore"
    ignore.write_text("local-entry\n", encoding="utf-8")

    preview = CliRunner().invoke(
        cli,
        ["view", "migrate", str(notebook), "--dry-run"],
    )

    result = CliRunner().invoke(
        cli,
        ["view", "migrate", str(notebook), "--format", "json"],
    )

    assert preview.exit_code == 0, preview.output
    assert preview.output.count(f"update {ignore}") == 1
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["views"] == ["dashboard"]
    assert payload["dry_run"] is False
    assert payload["updated"] == [str(ignore)]
    assert load_studio(notebook).view("dashboard").provider == "marimo-studio/vanilla"
