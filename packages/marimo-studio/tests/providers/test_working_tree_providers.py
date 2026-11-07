"""Protect build identity for providers installed from a working tree."""

from __future__ import annotations

import json
import os
from pathlib import Path, PurePosixPath

import pytest

import marimo_studio.view_providers._host as providers_module
from marimo_studio._server.development.source_changes import SourceChangeProducer
from marimo_studio._views.build import build_view_project_sync, publish_view
from marimo_studio._workspace import load_studio
from marimo_studio._workspace.project_manifest import encode_view_manifest
from marimo_studio.view_providers._host.registry import ProviderRegistry

from ..app_helpers import configured

_PROVIDER = """
from pathlib import PurePosixPath

from marimo_studio.view_providers import (
    BuildInput,
    BuildResult,
    ProjectInspection,
    ProviderAvailability,
    ProviderInfo,
    SourceDocument,
)

HEADING = "{heading}"


class Provider:
    info = ProviderInfo(title="Tree", summary="Builds one page.")

    def availability(self):
        return ProviderAvailability(True)

    def starters(self):
        return ()

    def create(self, starter, context):
        raise NotImplementedError

    def inspect(self, request):
        return ProjectInspection(
            documents=(SourceDocument(PurePosixPath("index.html"), "html", "edit"),),
            inputs=(BuildInput(PurePosixPath("index.html"), "file"),),
        )

    def build(self, request):
        page = request.staging_root / "index.html"
        page.write_text(
            "<!doctype html><html><head></head><body>"
            f"<main id='app-shell'><h1>{{HEADING}}</h1></main></body></html>",
            encoding="utf-8",
        )
        return BuildResult(PurePosixPath("index.html"), ())


provider = Provider()
"""


def _install(root: Path, direct_url: dict[str, object] | None) -> Path:
    """Install `tree-views` with its package in `root/src` and return the module."""
    package = root / "src" / "tree_views"
    package.mkdir(parents=True)
    module = package / "__init__.py"
    module.write_text(_PROVIDER.format(heading="First"), encoding="utf-8")
    metadata = root / "site" / "tree_views-1.0.0.dist-info"
    metadata.mkdir(parents=True)
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: tree-views\nVersion: 1.0.0\n",
        encoding="utf-8",
    )
    (metadata / "entry_points.txt").write_text(
        "[marimo_studio.view_provider]\npage = tree_views:provider\n",
        encoding="utf-8",
    )
    if direct_url is not None:
        (metadata / "direct_url.json").write_text(
            json.dumps(direct_url), encoding="utf-8"
        )
    return module


def _page(notebook_path: Path) -> str:
    project = load_studio(notebook_path).views["dashboard"]
    with build_view_project_sync(project) as lease:
        return lease.read_bytes(PurePosixPath("index.html")).decode()


def _dashboard_with_provider(
    notebook_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    direct_url: dict[str, object] | None,
) -> Path:
    """Point the dashboard view at an installed `tree-views` and return its module."""
    module = _install(tmp_path / "provider", direct_url)
    roots = (tmp_path / "provider" / "src", tmp_path / "provider" / "site")
    for root in roots:
        monkeypatch.syspath_prepend(str(root))
    # Each isolated provider operation imports the package in a new process.
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join(str(root) for root in roots))
    studio = configured(notebook_path)
    studio.views["dashboard"].manifest.write_text(
        encode_view_manifest("tree-views/page"), encoding="utf-8"
    )
    monkeypatch.setattr(providers_module, "_REGISTRY", ProviderRegistry.discover())
    return module


@pytest.mark.parametrize(
    ("direct_url", "rebuilt"),
    [
        pytest.param(
            {"url": "file:///work/tree-views", "dir_info": {"editable": True}},
            "<h1>Second</h1>",
            id="editable",
        ),
        pytest.param(
            {"url": "file:///work/tree-views", "dir_info": {}},
            "<h1>Second</h1>",
            id="directory",
        ),
        pytest.param(
            {"url": "https://example.com/tree_views-1.0.0.whl", "archive_info": {}},
            "<h1>First</h1>",
            id="archive",
        ),
        pytest.param(None, "<h1>First</h1>", id="index"),
    ],
)
def test_editing_a_working_tree_provider_rebuilds_its_view(
    notebook_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    direct_url: dict[str, object] | None,
    rebuilt: str,
) -> None:
    module = _dashboard_with_provider(notebook_path, tmp_path, monkeypatch, direct_url)

    assert "<h1>First</h1>" in _page(notebook_path)
    module.write_text(_PROVIDER.format(heading="Second"), encoding="utf-8")

    assert rebuilt in _page(notebook_path)


def test_source_monitor_reports_an_edit_to_a_working_tree_provider(
    notebook_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _dashboard_with_provider(
        notebook_path,
        tmp_path,
        monkeypatch,
        {"url": "file:///work/tree-views", "dir_info": {"editable": True}},
    )
    monitor = SourceChangeProducer(load_studio(notebook_path), "dashboard")
    assert module.parent in monitor.watch_plan.roots
    assert monitor.poll() is None

    module.write_text(_PROVIDER.format(heading="Second"), encoding="utf-8")
    change = monitor.poll()
    project, inspection, input_id = monitor.catalog()

    assert change is not None and change.kind == "project"
    with publish_view(
        project, "development", inspection=inspection, input_id=input_id
    ) as lease:
        assert (
            "<h1>Second</h1>" in lease.read_bytes(PurePosixPath("index.html")).decode()
        )
