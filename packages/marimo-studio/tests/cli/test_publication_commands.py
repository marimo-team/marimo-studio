from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from marimo_studio._cli import cli
from marimo_studio._views.api import prepare_view
from marimo_studio.authoring import open_workspace
from marimo_studio.errors import (
    ConfigurationError,
    SourceConflictError,
    ViewProjectError,
    WorkspaceGenerationConflictError,
)


def test_cli_coordinates_filesystem_edits_with_saved_workspace_api(
    notebook_path: Path,
) -> None:
    setup = prepare_view(notebook_path)
    runner = CliRunner()

    view = open_workspace(notebook_path).view("dashboard")
    first = asyncio.run(view.build())
    held = runner.invoke(
        cli,
        [
            "view",
            "hold",
            "dashboard",
            "--target",
            str(notebook_path),
            "--owner",
            "filesystem-editor",
            "--json",
        ],
    )
    assert held.exit_code == 0, held.output
    token = json.loads(held.stdout)["token"]

    async def edit() -> None:
        original = await view.read("index.html")
        path = setup.root / "index.html"
        path.write_text(
            original.content.replace("<title>", "<title>Revised "), encoding="utf-8"
        )
        current = await view.read("index.html")
        with pytest.raises(SourceConflictError):
            await view.write(
                "index.html", original.content, expected_revision=original.revision
            )
        with pytest.raises(ViewProjectError):
            await view.build()
        inspected = await view.inspect()
        assert inspected.build is not None
        assert inspected.build.revision == first.revision
        await view.release_publication(token)
        updated = await view.build()
        assert updated.revision != first.revision
        await view.write(
            "index.html", original.content, expected_revision=current.revision
        )
        restored = await view.build()
        assert restored.revision == first.revision

    asyncio.run(edit())


def test_cli_release_rejects_another_editors_token(notebook_path: Path) -> None:
    prepare_view(notebook_path)
    view = open_workspace(notebook_path).view("dashboard")
    hold = asyncio.run(view.hold_publication(owner="author"))
    runner = CliRunner()
    rejected = runner.invoke(
        cli,
        [
            "view",
            "release",
            "dashboard",
            "--target",
            str(notebook_path),
            "--token",
            "unrelated",
        ],
    )
    assert isinstance(rejected.exception, ConfigurationError)
    released = runner.invoke(
        cli,
        [
            "view",
            "release",
            "dashboard",
            "--target",
            str(notebook_path),
            "--token",
            hold.token,
            "--json",
        ],
    )
    assert released.exit_code == 0, released.output
    assert json.loads(released.stdout)["hold"]["status"] == "released"


@pytest.mark.parametrize("invalid_view", ["dashboard", "other"])
def test_publication_coordination_survives_incomplete_view_manifests(
    notebook_path: Path,
    invalid_view: str,
) -> None:
    setup = prepare_view(notebook_path)
    prepare_view(notebook_path, "other")
    view = open_workspace(notebook_path).view("dashboard")
    hold = asyncio.run(view.hold_publication(owner="source editor"))
    manifest = setup.root.parent / invalid_view / "view.toml"
    manifest.write_text("provider = [", encoding="utf-8")

    if invalid_view == "dashboard":
        repair = open_workspace(notebook_path).view("dashboard")
        inspected = asyncio.run(repair.inspect())
        assert inspected.publication_hold == hold

    released = asyncio.run(view.release_publication(hold.token))
    assert released is not None
    assert released.status == "released"
    retry = asyncio.run(view.hold_publication(owner="repair editor"))
    result = CliRunner().invoke(
        cli,
        [
            "view",
            "release",
            "dashboard",
            "--target",
            str(notebook_path),
            "--token",
            retry.token,
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["hold"]["status"] == "released"
    assert manifest.read_text(encoding="utf-8") == "provider = ["


def test_absent_view_handle_cannot_hold_a_later_view(notebook_path: Path) -> None:
    prepare_view(notebook_path)
    absent = open_workspace(notebook_path).view("later")
    prepare_view(notebook_path, "later")

    with pytest.raises(WorkspaceGenerationConflictError):
        asyncio.run(absent.hold_publication(owner="stale editor"))
