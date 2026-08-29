"""Shared project setup for built-in Deno provider tests."""

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
    provider_id: str,
    *,
    starter_key: str = "default",
) -> tuple[Path, ViewProject]:
    starter = next(item for item in provider.starters() if item.key == starter_key)
    provider_name = provider_id.rsplit("/", 1)[-1]
    suffix = "" if starter_key == "default" else f"-{starter_key}"
    root = tmp_path / f"{provider_name}{suffix}"
    files = provider.create(
        starter,
        StarterContext("research-view", "nga"),
    )
    write_plan(root, files, provider_id)
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
