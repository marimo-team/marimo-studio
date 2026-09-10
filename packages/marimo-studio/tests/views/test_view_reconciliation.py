from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path, PurePosixPath

import pytest

from marimo_studio._views.inspect import inspect_view
from marimo_studio.authoring import open_workspace
from marimo_studio.errors import MarimoStudioError

from ..app_helpers import published_dashboard


def test_inspection_reconciles_filesystem_and_managed_source_edits(
    notebook_path: Path,
) -> None:
    studio = published_dashboard(notebook_path)
    view = open_workspace(notebook_path).view("dashboard")
    before = asyncio.run(view.inspect())
    root = before.root
    page = root / "index.html"
    page.write_text(
        page.read_text().replace("</head>", '<script src="story.js"></script></head>')
    )
    script = root / "story.js"
    script.write_text('document.title = "Athlete story";\n')

    changed = asyncio.run(view.inspect())
    assert changed.freshness == "stale"
    assert changed.project_revision != before.project_revision
    assert changed.published_project_revision == before.project_revision
    assert changed.latest_build.phase == "published"
    assert changed.build == before.build
    assert changed.changes_since(before).to_dict() == {
        "added": ["story.js"],
        "modified": ["index.html"],
        "deleted": [],
    }
    document = asyncio.run(view.read("story.js"))
    observed = next(
        item for item in changed.files if item.path == PurePosixPath("story.js")
    )
    assert document.revision == observed.revision
    assert observed.revision is not None
    asyncio.run(
        view.write(
            "story.js",
            'document.title = "Updated story";\n',
            expected_revision=observed.revision,
        )
    )
    written = asyncio.run(view.inspect())
    assert written.changes_since(changed).modified == (PurePosixPath("story.js"),)
    script.unlink()
    page.write_text(page.read_text().replace('<script src="story.js"></script>', ""))
    deleted = asyncio.run(view.inspect())
    assert deleted.changes_since(written).deleted == (PurePosixPath("story.js"),)
    assert studio.view("dashboard").root == changed.root


def test_incomplete_discovery_preserves_missing_file_and_last_publication(
    notebook_path: Path,
) -> None:
    published_dashboard(notebook_path)
    view = open_workspace(notebook_path).view("dashboard")
    before = asyncio.run(view.inspect())
    page = before.root / "index.html"
    page.write_text(
        page.read_text().replace("</head>", '<script src="missing.js"></script></head>')
    )
    with pytest.raises(MarimoStudioError):
        asyncio.run(view.build())
    failed = asyncio.run(view.inspect())
    assert failed.build == before.build
    assert failed.freshness == "stale"
    assert failed.latest_build.diagnostics
    assert not failed.files_complete
    assert failed.project_revision is None
    assert any(
        item.path == PurePosixPath("missing.js") and item.revision is None
        for item in failed.files
    )
    with pytest.raises(ValueError, match="complete source inventories"):
        failed.changes_since(before)

    (before.root / "missing.js").write_text('document.title = "Repaired";\n')
    repaired = asyncio.run(view.inspect())
    assert repaired.files_complete
    assert repaired.project_revision is not None
    assert repaired.build == before.build
    assert repaired.latest_build.diagnostics == failed.latest_build.diagnostics
    asyncio.run(view.build())
    assert asyncio.run(view.inspect()).freshness == "current"


def test_binary_inputs_are_compared_by_bytes(notebook_path: Path) -> None:
    published_dashboard(notebook_path)
    view = open_workspace(notebook_path).view("dashboard")
    root = asyncio.run(view.inspect()).root
    page = root / "index.html"
    page.write_text(
        page.read_text().replace("</head>", '<script src="story.js"></script></head>')
    )
    payload = b"\x89PNG\xff\x00"
    (root / "story.js").write_bytes(payload)
    inspected = asyncio.run(view.inspect())
    assert (
        next(
            item.revision
            for item in inspected.files
            if item.path == PurePosixPath("story.js")
        )
        == f"sha256:{hashlib.sha256(payload).hexdigest()}"
    )


def test_manifest_parse_failure_has_repair_document_and_last_publication(
    notebook_path: Path,
) -> None:
    studio = published_dashboard(notebook_path)
    before = asyncio.run(inspect_view(studio, "dashboard"))
    manifest = before.root / "view.toml"
    original = manifest.read_text()
    manifest.write_text("provider = [")
    invalid = asyncio.run(inspect_view(studio, "dashboard"))
    assert [item.path.as_posix() for item in invalid.documents] == ["view.toml"]
    assert invalid.files[0].revision is not None
    assert invalid.build == before.build
    assert invalid.freshness == "stale"
    assert not invalid.files_complete
    manifest.write_text(original)
    assert asyncio.run(inspect_view(studio, "dashboard")).freshness == "current"


def test_inspection_rejects_source_changes_during_provider_observation(
    notebook_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from marimo_studio._views import inspect as inspection_module
    from marimo_studio.view_providers import ProjectInspection, ViewProject

    published_dashboard(notebook_path)
    view = open_workspace(notebook_path).view("dashboard")
    original = inspection_module.inspect_view_project
    calls = 0

    async def inspect_then_edit(project: ViewProject) -> ProjectInspection:
        nonlocal calls
        result = await original(project)
        calls += 1
        if calls == 2:
            page = project.root / "index.html"
            page.write_text(page.read_text() + "\n<p>Concurrent edit</p>\n")
        return result

    monkeypatch.setattr(inspection_module, "inspect_view_project", inspect_then_edit)
    with pytest.raises(MarimoStudioError, match="changed during inspection"):
        asyncio.run(view.inspect())


def test_public_inspection_exposes_manifest_repair_and_rejects_stale_owners(
    notebook_path: Path,
) -> None:
    from marimo_studio.errors import WorkspaceGenerationConflictError

    published_dashboard(notebook_path)
    previous = open_workspace(notebook_path).view("dashboard")
    before = asyncio.run(previous.inspect())
    manifest = before.root / "view.toml"
    valid = manifest.read_text()
    manifest.write_text("provider = [")
    with pytest.raises(WorkspaceGenerationConflictError):
        asyncio.run(previous.inspect())

    view = open_workspace(notebook_path).view("dashboard")
    invalid = asyncio.run(view.inspect())
    assert invalid.provider is None
    assert invalid.build == before.build
    assert invalid.latest_build == before.latest_build
    assert invalid.freshness == "stale"
    document = asyncio.run(view.read("view.toml"))
    assert invalid.files[0].revision == document.revision
    asyncio.run(view.write("view.toml", valid, expected_revision=document.revision))
    repaired = asyncio.run(open_workspace(notebook_path).view("dashboard").inspect())
    assert repaired.freshness == "current"


def test_invalid_sibling_manifest_is_reported_as_workspace_failure(
    notebook_path: Path,
) -> None:
    from marimo_studio._views.api import prepare_view
    from marimo_studio.errors import ConfigurationError

    studio = published_dashboard(notebook_path)
    prepare_view(notebook_path, "other")
    sibling = studio.view_root / "other" / "view.toml"
    sibling.write_text("provider = [")
    with pytest.raises(ConfigurationError, match=r"view\.toml"):
        asyncio.run(open_workspace(notebook_path).view("dashboard").inspect())


def test_unbuilt_view_manifest_can_be_inspected_for_repair(notebook_path: Path) -> None:
    from ..app_helpers import created_one_view

    studio = created_one_view(notebook_path)
    studio.view("dashboard").manifest.write_text("provider = [")
    inspected = asyncio.run(open_workspace(notebook_path).view("dashboard").inspect())
    assert inspected.build is None
    assert inspected.latest_build.phase == "unbuilt"
    assert inspected.freshness == "failed"
    assert inspected.files[0].path == PurePosixPath("view.toml")
