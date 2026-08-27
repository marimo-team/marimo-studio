"""Shared project scaffolding for built-in Deno provider tests."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path, PurePosixPath

from marimo_studio._views.inspection import inspection_request
from marimo_studio._workspace.project_manifest import (
    encode_view_manifest,
    load_view_project,
)
from marimo_studio.view_providers import (
    BuildRequest,
    BuildResult,
    ProjectInspection,
    StarterContext,
    ViewProject,
    ViewProvider,
)


def write_plan(
    root: Path,
    files: Mapping[PurePosixPath, bytes],
    provider: ViewProvider,
    provider_key: str,
) -> None:
    for relative, content in files.items():
        path = root.joinpath(*relative.parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    (root / "view.toml").write_text(
        encode_view_manifest(provider_key),
        encoding="utf-8",
    )


def project(
    tmp_path: Path,
    provider: ViewProvider,
    template_id: str,
) -> tuple[Path, ViewProject]:
    starter_key = template_id.rsplit(":", 1)[-1].rsplit("/", 1)[-1]
    root = tmp_path / starter_key
    files = provider.create(
        provider.starters()[0],
        StarterContext("research-view", "nga"),
    )
    write_plan(root, files, provider, f"marimo-studio/{starter_key}")
    return root, load_view_project(root)


def inspect_provider(
    provider: ViewProvider,
    project: ViewProject,
) -> ProjectInspection:
    return provider.inspect(inspection_request(project))


def build_provider(
    provider: ViewProvider,
    request: BuildRequest,
) -> BuildResult:
    return provider.build(request)
