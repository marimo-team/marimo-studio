"""Protect installed browser entry budgets through emitted import metadata."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from marimo_studio._release_checks.browser_assets import browser_asset_graphs


@pytest.mark.parametrize("transitive_dynamic_imports", [False, True])
def test_first_load_budget_follows_transitive_static_imports(
    tmp_path: Path, transitive_dynamic_imports: bool
) -> None:
    assets = tmp_path / "browser"
    (assets / "chunks").mkdir(parents=True)
    session = "../../packages/marimo-frontend/src/upstream/session.ts"
    server = "../../packages/presentation/src/runtime/server.ts"
    wasm = "../../packages/presentation/src/runtime/wasm.ts"
    source_editor = "../../packages/studio/src/features/source-editor/SourceEditor.tsx"
    manifest: dict[str, dict[str, object]] = {
        "runtime": {
            "file": "runtime.js",
            "isEntry": True,
            "imports": ["shared"],
            "dynamicImports": [session, server, wasm, "lazy"],
        },
        "studio": {
            "file": "studio.js",
            "isEntry": True,
            "imports": ["leaf"],
            "assets": ["assets/brand.svg"],
            "dynamicImports": [source_editor],
        },
        "host-session": {
            "file": "host-session-handoff.js",
            "isEntry": True,
            "imports": ["shared"],
        },
        "notebook-entry": {"file": "notebook-entry.js", "isEntry": True},
        "dev": {"file": "dev-reload.js", "isEntry": True, "imports": ["shared"]},
        "shared": {"file": "chunks/shared.js", "imports": ["leaf"]},
        "leaf": {"file": "chunks/leaf.js"},
        session: {"file": "chunks/session.js"},
        server: {
            "file": "chunks/server.js",
            "assets": ["assets/server.svg"],
        },
        wasm: {"file": "chunks/wasm.js"},
        source_editor: {"file": "chunks/source-editor.js"},
        "lazy": {"file": "chunks/lazy.js"},
    }
    if transitive_dynamic_imports:
        manifest["runtime"]["dynamicImports"] = ["lazy"]
        manifest["studio"]["dynamicImports"] = []
        manifest["leaf"]["dynamicImports"] = [session, server, wasm, source_editor]
    (assets / "entry-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    for relative in (
        "runtime.js",
        "runtime.css",
        "studio.js",
        "studio.css",
        "dev-reload.js",
        "host-session-handoff.js",
        "notebook-entry.js",
        "chunks/shared.js",
        "chunks/leaf.js",
        "chunks/session.js",
        "chunks/server.js",
        "chunks/wasm.js",
        "chunks/source-editor.js",
        "chunks/lazy.js",
        "assets/brand.svg",
        "assets/server.svg",
    ):
        path = assets / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative, encoding="utf-8")

    entry_graphs, startup_graphs = browser_asset_graphs(assets)
    entries = {
        entry: {path.relative_to(assets).as_posix() for path in paths}
        for entry, paths in entry_graphs.items()
    }
    startups = {
        profile: {path.relative_to(assets).as_posix() for path in paths}
        for profile, paths in startup_graphs.items()
    }

    assert entries == {
        "notebook-entry.js": {"notebook-entry.js"},
        "dev-reload.js": {
            "dev-reload.js",
            "chunks/shared.js",
            "chunks/leaf.js",
        },
        "runtime.js": {
            "runtime.js",
            "runtime.css",
            "chunks/shared.js",
            "chunks/leaf.js",
        },
        "host-session-handoff.js": {
            "host-session-handoff.js",
            "chunks/shared.js",
            "chunks/leaf.js",
        },
        "studio.js": {"studio.js", "studio.css", "assets/brand.svg", "chunks/leaf.js"},
    }
    assert startups["server"] == {
        "runtime.js",
        "runtime.css",
        "chunks/shared.js",
        "chunks/leaf.js",
        "chunks/session.js",
        "chunks/server.js",
        "assets/server.svg",
    }
    assert startups["server-dev"] == {*startups["server"], "dev-reload.js"}
    assert startups["studio-source"] == {
        "studio.js",
        "studio.css",
        "assets/brand.svg",
        "chunks/leaf.js",
        "chunks/source-editor.js",
    }
    assert startups["wasm"] == {
        "runtime.js",
        "runtime.css",
        "chunks/shared.js",
        "chunks/leaf.js",
        "chunks/session.js",
        "chunks/wasm.js",
    }
    assert startups["wasm-dev"] == {*startups["wasm"], "dev-reload.js"}
