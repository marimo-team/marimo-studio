"""Shared fixtures for immutable artifact contract tests."""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any

import pytest

from marimo_studio._artifacts.paths import artifact_root
from marimo_studio._artifacts.records import ViewArtifact
from marimo_studio._views.build import publish_view as publish_artifact_lease
from marimo_studio._workspace.project_manifest import (
    encode_view_manifest,
    load_view_project,
)
from marimo_studio.view_providers import BuildProfile, BuildRequest, ViewProject
from marimo_studio.view_providers._host import provider_registry


def publish_artifact(
    project: ViewProject,
    profile: BuildProfile,
) -> ViewArtifact:
    with publish_artifact_lease(project, profile) as lease:
        return lease.artifact


def project(tmp_path: Path) -> ViewProject:
    root = tmp_path / "view"
    root.mkdir(parents=True)
    (root / "view.toml").write_text(
        encode_view_manifest("marimo-studio/vanilla"),
        encoding="utf-8",
    )
    (root / "index.html").write_text(
        "<!doctype html><html><head></head><body>"
        '<main id="app-shell"><span mo-value="summary"></span></main>'
        "</body></html>",
        encoding="utf-8",
    )
    (root / "app.css").write_text("body { color: black; }\n", encoding="utf-8")
    return load_view_project(root)


def manifest_path(artifact: ViewArtifact) -> Path:
    return artifact.root.parent / "artifact.json"


def profile_path(project: ViewProject, profile: str = "development") -> Path:
    return artifact_root(project) / f"{profile}.json"


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def change_document(project: ViewProject, label: str) -> None:
    document = project.root / "index.html"
    document.write_text(
        document.read_text(encoding="utf-8").replace(
            "</main>", f"<p>{label}</p></main>"
        ),
        encoding="utf-8",
    )


def add_provider_outputs(
    monkeypatch: pytest.MonkeyPatch,
    project: ViewProject,
    outputs: Mapping[PurePosixPath, bytes],
) -> None:
    """Extend one test build with explicit synthetic browser files."""
    provider = provider_registry().get(project.provider)
    build = provider.build

    def build_with_outputs(request: BuildRequest):
        report = build(request)
        for relative, content in outputs.items():
            destination = request.staging_root.joinpath(*relative.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
        return report

    monkeypatch.setattr(provider, "build", build_with_outputs)


def wait_for_file(path: Path) -> None:
    deadline = time.monotonic() + 5
    while not path.exists():
        if time.monotonic() >= deadline:
            raise AssertionError(f"Timed out waiting for {path.name}")
        time.sleep(0.01)
