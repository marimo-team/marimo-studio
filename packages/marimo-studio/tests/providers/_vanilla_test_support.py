from __future__ import annotations

from dataclasses import replace
from pathlib import Path, PurePosixPath

from marimo_studio._workspace.project_manifest import (
    encode_view_manifest,
    load_view_project,
)
from marimo_studio.view_providers import ViewProject
from marimo_studio.view_providers._bundled.vanilla import provider

from ..provider_test_support import provider_starter_context


def _write_files(root: Path, files: dict[PurePosixPath, bytes]) -> ViewProject:
    for relative, content in files.items():
        path = root.joinpath(*relative.parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    (root / "view.toml").write_text(
        encode_view_manifest("marimo-studio/vanilla"),
        encoding="utf-8",
    )
    return replace(load_view_project(root), options={"entrypoint": "index.html"})


def _project(tmp_path: Path) -> ViewProject:
    plan = provider.create(
        provider.starters()[0],
        provider_starter_context(
            tmp_path,
            view_name="overview",
            notebook_name="analysis",
        ),
    )
    return _write_files(tmp_path / "overview", dict(plan.files))


def _project_with_local_sources(
    tmp_path: Path,
    *,
    css: str,
    javascript: str,
) -> ViewProject:
    project = _project(tmp_path)
    source = project.root / "index.html"
    source.write_text(
        source.read_text(encoding="utf-8").replace(
            "</head>",
            """<link rel="stylesheet" href="styles/app.css" />
            <script type="module" src="scripts/app.js"></script>
            </head>""",
        ),
        encoding="utf-8",
    )

    styles = project.root / "styles" / "app.css"
    script = project.root / "scripts" / "app.js"
    styles.parent.mkdir()
    script.parent.mkdir()
    styles.write_text(css, encoding="utf-8")
    script.write_text(javascript, encoding="utf-8")
    return project
