"""Verify the installed Marimo Studio distribution contract."""

from __future__ import annotations

import argparse
import asyncio
import gzip
import importlib.util
import json
import os
import subprocess
import sys
from hashlib import sha256
from importlib import resources
from importlib.metadata import distribution, version
from pathlib import Path
from tempfile import TemporaryDirectory

import agent_plugins
import marimo_studio
import marimo_studio.agent as studio_agent
import tomlkit
from marimo_studio._delivery.assets import runtime_assets_path

_DISTRIBUTION = "marimo-studio"
_ENTRY_POINTS = {
    ("console_scripts", "marimo-studio"),
    ("marimo.agent.capability", "studio"),
    ("marimo.kernel.lifespan", "marimo-studio"),
    ("marimo.server.asgi.middleware", "marimo-studio"),
    ("marimo_studio.view_provider", "react"),
    ("marimo_studio.view_provider", "svelte"),
    ("marimo_studio.view_provider", "vanilla"),
}
_REQUIRED_ASSETS = {
    "build-meta.json",
    "runtime.css",
    "runtime.js",
    "studio.css",
    "studio.js",
}
_MAX_BROWSER_ASSET_BYTES = 24 * 1024 * 1024
_MAX_BROWSER_ASSET_FILES = 400
_MAX_ENTRY_ASSET_BYTES = 600 * 1024
_MAX_ENTRY_GZIP_BYTES = 120 * 1024
_NOTEBOOK = """import marimo

app = marimo.App()

@app.cell
def result():
    result = "ready"
    result
    return (result,)

if __name__ == "__main__":
    app.run()
"""


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify one installed Marimo Studio distribution.",
    )
    parser.add_argument(
        "--deno", action="store_true", help="Build React and Svelte views."
    )
    parser.add_argument(
        "--expected-version", help="Require this installed package version."
    )
    parser.add_argument(
        "--expected-plugin-digests",
        type=Path,
        help="Compare installed Agent Plugin files with this digest map.",
    )
    return parser.parse_args()


def _verify_entry_points() -> None:
    installed = distribution(_DISTRIBUTION)
    points = {(point.group, point.name): point for point in installed.entry_points}
    if set(points) != _ENTRY_POINTS:
        missing = sorted(_ENTRY_POINTS - set(points))
        extra = sorted(set(points) - _ENTRY_POINTS)
        raise AssertionError(
            f"Installed entry points differ: missing={missing}, extra={extra}"
        )
    for point in points.values():
        point.load()


def _verify_public_imports(notebook: Path) -> None:
    program = """
from importlib import resources
import marimo_studio
import marimo_studio.agent
import marimo_studio.asgi
import marimo_studio.errors
import marimo_studio.view_providers
import agent_plugins

assert callable(marimo_studio.create_asgi_app)
assert callable(marimo_studio.agent.open)
assert callable(marimo_studio.asgi.app)
assert resources.files("marimo_studio").joinpath("py.typed").is_file()
assert set(marimo_studio.__all__) == {
    "LENS_TARGET_SELECTOR", "ASGIApp", "CellConfigSpec", "CellRef", "CellSpec",
    "NotebookSpec", "SourceSpan", "create_asgi_app", "inspect_notebook",
}
assert set(marimo_studio.agent.__all__) == {
    "AnalysisAction", "BindingResult", "CellSelector", "InspectionResult", "Publication", "Starter",
    "StudioDiagnostic", "StudioOverview", "ValidationLevel", "ValidationReport",
    "View", "ViewActivationResult", "ViewDocument", "ViewFreshness",
    "ViewInspection", "ViewOverview", "Workspace", "open",
}
assert set(marimo_studio.view_providers.__all__) == {
    "PROVIDER_API_VERSION", "BuildProfile", "BuildRequest", "BuildResult",
    "DocumentAccess", "InspectionRequest", "JsonValue", "MountDeclaration", "ProjectDiagnostic",
    "ProjectInput", "ProjectInputKind", "ProjectInspection", "ProjectionKind",
    "ProviderAvailability", "ProviderCancellation", "ProviderCommandResult",
    "ProviderInfo", "ProviderRunner", "ProviderStarter", "SourceDocument",
    "SourceLocation", "StarterContext", "ViewProject", "ViewProvider",
    "mount_attribute",
}
assert set(marimo_studio.errors.__all__) == {
    "AgentRequestError", "BindingError", "CapabilityInputError", "ConfigurationError",
    "DependencyError", "LastViewError", "MarimoStudioError", "NotebookSourceError",
    "ProtocolError", "ProviderNotFoundError", "RuntimeSelectionError", "RuntimeTimeoutError",
    "SourceConflictError", "SourceEncodingError", "SourceNotFoundError", "SourceTooLargeError",
    "SourceValidationError", "StaticExportError", "ViewExistsError", "ViewNotFoundError",
    "ViewProjectError",
}
"""
    completed = subprocess.run(
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "MARIMO_STUDIO_NOTEBOOK": str(notebook)},
    )
    if completed.returncode != 0:
        raise AssertionError(
            "Installed public imports failed in a fresh process:\n"
            f"{completed.stdout}{completed.stderr}"
        )


def _verify_agent_plugin(expected_path: Path | None) -> None:
    installed = distribution(_DISTRIBUTION)
    files = installed.files or ()
    selected = [item for item in files if ".agent-plugin/" in str(item)]
    relative = [str(item).split(".agent-plugin/", 1)[1] for item in selected]
    if len(relative) != len(set(relative)):
        raise AssertionError("Installed Agent Plugin contains duplicate paths")
    actual = {
        path: sha256(Path(installed.locate_file(item)).read_bytes()).hexdigest()
        for path, item in zip(relative, selected, strict=True)
    }
    required = {
        "plugin.json",
        "skills/marimo-studio/SKILL.md",
        "skills/marimo-studio/agents/openai.yaml",
        "skills/marimo-studio/references/validation-and-handoff.md",
        "skills/marimo-studio/references/view-authoring.md",
    }
    if not required.issubset(actual):
        raise AssertionError(
            f"Missing installed Agent Plugin resources: {sorted(required - actual)}"
        )
    if expected_path is not None:
        expected = json.loads(expected_path.read_text(encoding="utf-8"))
        if actual != expected:
            raise AssertionError(
                "Installed Agent Plugin bytes differ from the source map"
            )
    plugin = agent_plugins.locate(_DISTRIBUTION)
    if plugin.manifest.name != _DISTRIBUTION:
        raise AssertionError(
            f"Agent Plugin discovery returned {plugin.manifest.name!r}"
        )
    if {skill.path.name for skill in plugin.skills} != {"marimo-studio"}:
        raise AssertionError(
            "Agent Plugin discovery returned an unexpected skill catalog"
        )


def _verify_browser_assets() -> None:
    root = runtime_assets_path()
    present = {path.name for path in root.iterdir() if path.is_file()}
    if not _REQUIRED_ASSETS.issubset(present):
        raise AssertionError(
            f"Missing browser assets: {sorted(_REQUIRED_ASSETS - present)}"
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
    files = tuple(path for path in root.rglob("*") if path.is_file())
    total_bytes = sum(path.stat().st_size for path in files)
    if len(files) > _MAX_BROWSER_ASSET_FILES or total_bytes > _MAX_BROWSER_ASSET_BYTES:
        raise AssertionError(
            f"Browser assets exceed the package budget: {len(files)} files, "
            f"{total_bytes} bytes"
        )
    entry_assets = tuple(
        root / name for name in ("runtime.js", "runtime.css", "studio.js", "studio.css")
    )
    entry_bytes = sum(path.stat().st_size for path in entry_assets)
    entry_gzip_bytes = sum(
        len(gzip.compress(path.read_bytes())) for path in entry_assets
    )
    if entry_bytes > _MAX_ENTRY_ASSET_BYTES or entry_gzip_bytes > _MAX_ENTRY_GZIP_BYTES:
        raise AssertionError(
            "Browser entry assets exceed the first-load budget: "
            f"{entry_bytes} raw bytes, {entry_gzip_bytes} gzip bytes"
        )
    build_meta = json.loads((root / "build-meta.json").read_text(encoding="utf-8"))
    release = json.loads(
        resources.files("marimo_studio._compat")
        .joinpath("release.json")
        .read_text(encoding="utf-8")
    )
    if build_meta.get("marimo") != {
        "repository": "https://github.com/marimo-team/marimo.git",
        **release,
    }:
        raise AssertionError(
            "Installed browser metadata does not match the pinned release"
        )


def _validate_cli(notebook: Path, view: str) -> None:
    completed = subprocess.run(
        [
            "marimo-studio",
            "validate",
            str(notebook),
            "--view",
            view,
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr)
    payload = json.loads(completed.stdout)
    if payload.get("ok") is not True:
        raise AssertionError(f"Installed CLI validation failed: {payload}")


def _verify_views(*, deno: bool) -> None:
    async def verify() -> None:
        with TemporaryDirectory() as directory:
            notebook = Path(directory) / "installed_check.py"
            notebook.write_text(_NOTEBOOK, encoding="utf-8")
            workspace = studio_agent.open(notebook=notebook)
            catalog = {item.id: item for item in await workspace.starters()}
            expected = {
                "marimo-studio/react:default",
                "marimo-studio/svelte:default",
                "marimo-studio/vanilla:default",
            }
            if set(catalog) != expected:
                raise AssertionError(
                    f"Unexpected installed starter catalog: {sorted(catalog)}"
                )
            if not deno:
                vanilla_starter = catalog["marimo-studio/vanilla:default"]
                if not vanilla_starter.availability.available:
                    raise AssertionError("Installed Vanilla starter is unavailable")
                vanilla = await workspace.ensure_view(
                    "dashboard",
                    starter=vanilla_starter,
                )
                _verify_public_imports(notebook)
                if importlib.util.find_spec("deno") is not None:
                    raise AssertionError(
                        "The base installation includes the Deno runtime"
                    )
                manifest = tomlkit.parse((await vanilla.read("view.toml")).content)
                if dict(manifest) != {
                    "schema": 1,
                    "provider": "marimo-studio/vanilla",
                }:
                    raise AssertionError(
                        f"Unexpected installed view manifest: {manifest}"
                    )
                await vanilla.build()
                if (await vanilla.inspect()).publication is None:
                    raise AssertionError(
                        "Installed Vanilla build did not publish an artifact"
                    )
                _validate_cli(notebook, "dashboard")
                return
            for view_name, identity in (
                ("react", "marimo-studio/react:default"),
                ("svelte", "marimo-studio/svelte:default"),
            ):
                if not catalog[identity].availability.available:
                    raise AssertionError(f"Installed {identity} starter is unavailable")
                view = await workspace.ensure_view(
                    view_name,
                    starter=catalog[identity],
                )
                await view.build()
                if (await view.inspect()).publication is None:
                    raise AssertionError(
                        f"Installed {identity} build did not publish an artifact"
                    )

    asyncio.run(verify())


def main() -> None:
    args = _arguments()
    installed_version = version(_DISTRIBUTION)
    if args.expected_version is not None and installed_version != args.expected_version:
        raise AssertionError(
            f"Installed version {installed_version} does not match {args.expected_version}"
        )
    if not callable(marimo_studio.create_asgi_app) or not callable(studio_agent.open):
        raise TypeError("Installed Python APIs are unavailable")
    _verify_entry_points()
    _verify_agent_plugin(args.expected_plugin_digests)
    _verify_browser_assets()
    _verify_views(deno=args.deno)
    print(
        json.dumps(
            {
                "deno": args.deno,
                "package": _DISTRIBUTION,
                "version": installed_version,
                "verified": True,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
