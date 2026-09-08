"""Validate installed browser assets and import-graph budgets."""

from __future__ import annotations

import gzip
import json
import re
from importlib.metadata import version as distribution_version
from pathlib import Path

REQUIRED_ASSETS = {
    "build-meta.json",
    "entry-manifest.json",
    "host-session-handoff.js",
    "runtime.css",
    "runtime.js",
    "studio.css",
    "studio.js",
}
MAX_ENTRY_GRAPH_BYTES = 850 * 1024
MAX_ENTRY_GRAPH_GZIP_BYTES = 225 * 1024
MAX_STARTUP_GRAPH_BYTES = 6_500 * 1024
MAX_STARTUP_GRAPH_GZIP_BYTES = 2_200 * 1024
MAX_STUDIO_STARTUP_BYTES = 1_300 * 1024
MAX_STUDIO_STARTUP_GZIP_BYTES = 375 * 1024
BROWSER_ENTRIES = {
    "dev-reload.js",
    "host-session-handoff.js",
    "runtime.js",
    "studio.js",
}
BROWSER_ENTRY_STYLES = {
    "runtime.js": ("runtime.css",),
    "studio.js": ("studio.css",),
}
RUNTIME_IMPORT_SUFFIXES = {
    "server": "/runtime/server.ts",
    "session": "/upstream/session.ts",
    "wasm": "/runtime/wasm.ts",
}
STUDIO_SOURCE_IMPORT_SUFFIX = "/features/source-editor/SourceEditor.tsx"
REMOVED_KATEX_ASSET = re.compile(r"(?:^|/)KaTeX_[^/]+\.(?:woff|ttf)$")


def browser_asset_graphs(
    root: Path,
) -> tuple[dict[str, tuple[Path, ...]], dict[str, tuple[Path, ...]]]:
    """Return transitive entry and startup asset graphs from Vite metadata."""
    manifest = json.loads((root / "entry-manifest.json").read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise TypeError("Browser entry manifest is not an object")
    entries: dict[str, str] = {}
    for key, chunk in manifest.items():
        if not isinstance(key, str) or not isinstance(chunk, dict):
            raise TypeError("Browser entry manifest contains an invalid chunk")
        file = chunk.get("file")
        if chunk.get("isEntry") is True and isinstance(file, str):
            entries[file] = key
    if set(entries) != BROWSER_ENTRIES:
        raise AssertionError(
            "Browser entry manifest differs: "
            f"expected={sorted(BROWSER_ENTRIES)}, actual={sorted(entries)}"
        )

    root = root.resolve()

    def asset(relative: object, *, emitted: bool = True) -> Path | None:
        if not isinstance(relative, str) or not relative:
            raise TypeError("Browser entry manifest contains an invalid asset path")
        path = (root / relative).resolve()
        if not path.is_relative_to(root):
            raise AssertionError(f"Browser entry asset is unavailable: {relative}")
        if not path.is_file():
            if not emitted and REMOVED_KATEX_ASSET.search(relative):
                return None
            raise AssertionError(f"Browser entry asset is unavailable: {relative}")
        return path

    def graph(
        roots: tuple[str, ...],
        styles: tuple[str, ...] = (),
        *,
        dynamic_imports: set[str] | None = None,
    ) -> tuple[Path, ...]:
        pending = list(roots)
        visited: set[str] = set()
        paths = {path for item in styles if (path := asset(item)) is not None}
        while pending:
            key = pending.pop()
            if key in visited:
                continue
            visited.add(key)
            chunk = manifest.get(key)
            if not isinstance(chunk, dict):
                raise TypeError(f"Browser entry import is unavailable: {key}")
            file = asset(chunk.get("file"))
            assert file is not None
            paths.add(file)
            css = chunk.get("css", [])
            assets = chunk.get("assets", [])
            imports = chunk.get("imports", [])
            dynamic = chunk.get("dynamicImports", [])
            if (
                not isinstance(css, list)
                or not isinstance(assets, list)
                or not isinstance(imports, list)
                or not isinstance(dynamic, list)
            ):
                raise TypeError(f"Browser entry chunk is malformed: {key}")
            paths.update(path for item in css if (path := asset(item)) is not None)
            paths.update(
                path
                for item in assets
                if (path := asset(item, emitted=False)) is not None
            )
            if not all(isinstance(item, str) for item in (*imports, *dynamic)):
                raise AssertionError(f"Browser entry imports are malformed: {key}")
            if dynamic_imports is not None:
                dynamic_imports.update(dynamic)
            pending.extend(imports)
        return tuple(sorted(paths))

    entry_imports: dict[str, set[str]] = {entry: set() for entry in entries}
    entry_graphs = {
        entry: graph(
            (key,),
            BROWSER_ENTRY_STYLES.get(entry, ()),
            dynamic_imports=entry_imports[entry],
        )
        for entry, key in sorted(entries.items())
    }
    runtime_key = entries["runtime.js"]
    dynamic_imports = entry_imports["runtime.js"]
    runtime_imports: dict[str, str] = {}
    for name, suffix in RUNTIME_IMPORT_SUFFIXES.items():
        matches = [
            item
            for item in dynamic_imports
            if isinstance(item, str) and item.endswith(suffix)
        ]
        if len(matches) != 1 or matches[0] not in manifest:
            raise AssertionError(f"Browser runtime {name} import is unavailable")
        runtime_imports[name] = matches[0]
    runtime_styles = BROWSER_ENTRY_STYLES["runtime.js"]
    dev_key = entries["dev-reload.js"]
    studio_key = entries["studio.js"]
    studio_source_imports = [
        item
        for item in entry_imports["studio.js"]
        if isinstance(item, str) and item.endswith(STUDIO_SOURCE_IMPORT_SUFFIX)
    ]
    if len(studio_source_imports) != 1 or studio_source_imports[0] not in manifest:
        raise AssertionError("Browser Studio source editor import is unavailable")
    startup_graphs = {
        "server": graph(
            (runtime_key, runtime_imports["session"], runtime_imports["server"]),
            runtime_styles,
        ),
        "server-dev": graph(
            (
                runtime_key,
                runtime_imports["session"],
                runtime_imports["server"],
                dev_key,
            ),
            runtime_styles,
        ),
        "studio-source": graph(
            (studio_key, studio_source_imports[0]),
            BROWSER_ENTRY_STYLES["studio.js"],
        ),
        "wasm": graph(
            (runtime_key, runtime_imports["session"], runtime_imports["wasm"]),
            runtime_styles,
        ),
        "wasm-dev": graph(
            (
                runtime_key,
                runtime_imports["session"],
                runtime_imports["wasm"],
                dev_key,
            ),
            runtime_styles,
        ),
    }
    return entry_graphs, startup_graphs


def verify_browser_assets(root: Path, release: dict[str, object]) -> None:
    """Validate installed browser contents, startup budgets, and provenance."""
    present = {path.name for path in root.iterdir() if path.is_file()}
    if not REQUIRED_ASSETS.issubset(present):
        raise AssertionError(
            f"Missing browser assets: {sorted(REQUIRED_ASSETS - present)}"
        )
    chunks = tuple((root / "chunks").glob("*.js"))
    workers = tuple((root / "assets").glob("*worker*.js"))
    if not chunks or not workers:
        raise AssertionError("Installed browser chunks or workers are missing")
    unsupported_katex = tuple(root.glob("assets/KaTeX_*.woff")) + tuple(
        root.glob("assets/KaTeX_*.ttf")
    )
    runtime_css = (root / "runtime.css").read_text(encoding="utf-8")
    if (
        unsupported_katex
        or 'format("woff")' in runtime_css
        or 'format("truetype")' in runtime_css
    ):
        raise AssertionError(
            "Installed KaTeX assets violate the WOFF2 browser contract"
        )
    entry_graphs, startup_graphs = browser_asset_graphs(root)
    for entry, entry_graph in entry_graphs.items():
        entry_bytes = sum(path.stat().st_size for path in entry_graph)
        entry_gzip_bytes = sum(
            len(gzip.compress(path.read_bytes())) for path in entry_graph
        )
        if (
            entry_bytes > MAX_ENTRY_GRAPH_BYTES
            or entry_gzip_bytes > MAX_ENTRY_GRAPH_GZIP_BYTES
        ):
            raise AssertionError(
                f"Browser entry {entry} exceeds the first-load graph budget: "
                f"{entry_bytes} raw bytes, {entry_gzip_bytes} gzip bytes"
            )
    for profile, startup_graph in startup_graphs.items():
        startup_bytes = sum(path.stat().st_size for path in startup_graph)
        startup_gzip_bytes = sum(
            len(gzip.compress(path.read_bytes())) for path in startup_graph
        )
        maximum_bytes = (
            MAX_STUDIO_STARTUP_BYTES
            if profile == "studio-source"
            else MAX_STARTUP_GRAPH_BYTES
        )
        maximum_gzip_bytes = (
            MAX_STUDIO_STARTUP_GZIP_BYTES
            if profile == "studio-source"
            else MAX_STARTUP_GRAPH_GZIP_BYTES
        )
        if startup_bytes > maximum_bytes or startup_gzip_bytes > maximum_gzip_bytes:
            raise AssertionError(
                f"Browser {profile} startup exceeds the first-load graph budget: "
                f"{startup_bytes} raw bytes, {startup_gzip_bytes} gzip bytes"
            )
    build_meta = json.loads((root / "build-meta.json").read_text(encoding="utf-8"))
    expected_marimo = {
        "repository": "https://github.com/marimo-team/marimo.git",
        "version": release.get("version"),
        "commit": release.get("commit"),
        "patchSha256": release.get("frontendPatchSha256"),
    }
    if build_meta.get("marimo") != expected_marimo:
        raise AssertionError(
            "Installed browser metadata does not match the pinned release"
        )
    expected_export = {"version": distribution_version("marimo-export")}
    if build_meta.get("marimoExport") != expected_export:
        raise AssertionError(
            "Installed browser metadata does not match the Python marimo-export"
        )
