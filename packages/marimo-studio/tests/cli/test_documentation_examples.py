"""Run copyable documentation examples through the APIs they document."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import cast

from marimo_studio._artifacts.repository import validate_document
from marimo_studio._views.inspection import inspection_request
from marimo_studio._workspace.project_manifest import (
    encode_view_manifest,
    load_view_project,
)
from marimo_studio.view_providers import ViewProvider
from marimo_studio.view_providers._host.registry import ProviderRegistry

from ..provider_test_support import (
    candidate,
    provider_build_request,
    provider_starter_context,
)


def _documentation_paths() -> tuple[Path, ...]:
    paths = {
        Path("README.md"),
        Path("packages/marimo-studio/README.md"),
        *Path("docs").rglob("*.md"),
        *Path("skills/marimo-studio").rglob("*.md"),
    }
    return tuple(sorted(path for path in paths if path.is_file()))


def _python_blocks(document: str) -> tuple[str, ...]:
    sections = document.split("```python\n")[1:]
    return tuple(section.split("\n```", 1)[0] for section in sections)


def test_every_python_example_compiles() -> None:
    compiled = 0
    for path in _documentation_paths():
        for block in _python_blocks(path.read_text(encoding="utf-8")):
            compile(block, str(path), "exec", flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)
            compiled += 1
    assert compiled > 0


def test_documented_provider_builds_a_complete_html_artifact(tmp_path) -> None:
    document = Path("docs/reference/provider-api.md").read_text(encoding="utf-8")
    source = _python_blocks(document.split("## Minimal provider", 1)[1])[0]
    namespace: dict[str, object] = {}
    exec(compile(source, "provider-api.md", "exec"), namespace)
    provider = cast(ViewProvider, namespace["provider"])
    registry = ProviderRegistry(
        (candidate("report", provider, distribution="acme-views"),)
    )
    installed = registry.get("acme-views/report")
    root = tmp_path / "report"
    root.mkdir()
    starter = installed.starters()[0]
    plan = installed.create(
        starter,
        provider_starter_context(tmp_path, view_name="report"),
    )
    for relative, payload in plan.files.items():
        path = root.joinpath(*relative.parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    (root / "view.toml").write_text(
        encode_view_manifest(installed.key),
        encoding="utf-8",
    )
    project = load_view_project(root)
    inspection = installed.inspect(inspection_request(project))
    staging = tmp_path / "staging"
    staging.mkdir()

    result = installed.build(
        provider_build_request(
            project,
            inspection,
            staging,
            cache_root=tmp_path / "cache-owner" / ".artifacts" / ".cache",
        )
    )

    assert result.document is not None
    validate_document(staging, result.document)
