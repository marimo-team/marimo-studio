"""Provide Svelte projects as editable Studio views.

The Svelte provider creates a complete TypeScript and Vite starter, shows
component and configuration files in Source, identifies cell, output, and value
mounts in Svelte templates, and builds browser files with the pinned Deno
toolchain for Studio to validate and publish.

Inspection records which documents may be edited and which inputs affect a
build. ``deno.lock`` and ``src/vite-env.d.ts`` remain read-only. Svelte,
TypeScript, and mount diagnostics point back to authored source, and every
mount records the notebook targets that source location may request.
"""

from __future__ import annotations

from pathlib import PurePosixPath

from marimo_studio.view_providers import (
    PROVIDER_API_VERSION,
    BuildRequest,
    BuildResult,
    InspectionRequest,
    ProjectInput,
    ProjectInspection,
    ProviderAvailability,
    ProviderInfo,
    ProviderStarter,
    StarterContext,
    StarterPlan,
    ViewProject,
)
from marimo_studio.view_providers._bundled import _deno
from marimo_studio.view_providers._bundled._deno.project import ProviderProjectSpec
from marimo_studio.view_providers._bundled._starters import (
    create_starter,
    provider_starters,
)
from marimo_studio.view_providers._bundled.deno_svelte.build import build_svelte
from marimo_studio.view_providers._bundled.deno_svelte.starters import (
    catalog as _STARTERS,
)

PROVIDER_KEY = "marimo-studio/svelte"
SVELTE_VERSION = "5.56.9"
SVELTE_PLUGIN_VERSION = "7.3.0"
SVELTE_CHECK_VERSION = "4.7.5"
VITE_VERSION = "8.2.1"
TYPESCRIPT_VERSION = "6.0.3"
PROJECTION_CONTRACT_VERSION = "svelte-projections-v2"
BUILD_CONTRACT_VERSION = "vite-svelte-artifact-v1"
_INPUT_SCOPE = (
    ProjectInput(PurePosixPath("src"), "directory"),
    ProjectInput(PurePosixPath("view.toml"), "file"),
    ProjectInput(PurePosixPath("package.json"), "file"),
    ProjectInput(PurePosixPath("deno.json"), "file"),
    ProjectInput(PurePosixPath("vite.config.ts"), "file"),
    ProjectInput(PurePosixPath("svelte.config.js"), "file"),
    ProjectInput(PurePosixPath("tsconfig.json"), "file"),
    ProjectInput(PurePosixPath("deno.lock"), "file"),
    ProjectInput(PurePosixPath("public"), "directory"),
)
_DOCUMENT_ROOTS = (PurePosixPath("AGENTS.md"), PurePosixPath("DESIGN.md"))
_REQUIRED = (
    "view.toml",
    "package.json",
    "svelte.config.js",
)
_EDITOR_LANGUAGES = {
    "AGENTS.md": "markdown",
    "DESIGN.md": "markdown",
    "deno.json": "json",
    "deno.lock": "json",
    "package.json": "json",
    "svelte.config.js": "javascript",
    "tsconfig.json": "json",
    "vite.config.ts": "typescript",
    ".css": "css",
    ".html": "html",
    ".js": "javascript",
    ".json": "json",
    ".mjs": "javascript",
    ".svelte": "svelte",
    ".svg": "xml",
    ".ts": "typescript",
}
_PROJECT = ProviderProjectSpec(
    provider_id=PROVIDER_KEY,
    analyzer_package="marimo_studio.view_providers._bundled.deno_svelte",
    input_scope=_INPUT_SCOPE,
    document_roots=_DOCUMENT_ROOTS,
    required_files=_REQUIRED,
    editor_languages=_EDITOR_LANGUAGES,
    read_only=frozenset({"deno.lock", "src/vite-env.d.ts"}),
    option_paths={
        "entrypoint": "src/index.html",
        "config": "deno.json",
        "lockfile": "deno.lock",
        "vite_config": "vite.config.ts",
        "tsconfig": "tsconfig.json",
    },
    analyzer_suffixes=frozenset({".js", ".mjs", ".ts", ".svelte"}),
    lockfile="deno.lock",
    build_fingerprint=(
        f"{_deno.DENO_VERSION}:{SVELTE_VERSION}:{SVELTE_PLUGIN_VERSION}:"
        f"{SVELTE_CHECK_VERSION}:{VITE_VERSION}:{TYPESCRIPT_VERSION}:"
        f"{PROJECTION_CONTRACT_VERSION}:{BUILD_CONTRACT_VERSION}"
    ),
)


class DenoSvelteProvider:
    """Inspect Svelte source and build one immutable Vite candidate."""

    info = ProviderInfo(
        title="Svelte",
        summary="Builds a Svelte project with the pinned Deno toolchain.",
        api_version=PROVIDER_API_VERSION,
    )

    def availability(self, project: ViewProject | None = None) -> ProviderAvailability:
        del project
        return _deno.deno_availability()

    def starters(self) -> tuple[ProviderStarter, ...]:
        return provider_starters(_STARTERS)

    def create(
        self,
        starter: ProviderStarter,
        context: StarterContext,
    ) -> StarterPlan:
        return create_starter(_STARTERS, starter, context)

    def inspect(self, request: InspectionRequest) -> ProjectInspection:
        return _PROJECT.inspect(request, self.availability(request.project))

    def build(self, request: BuildRequest) -> BuildResult:
        return build_svelte(
            request,
            _PROJECT,
            svelte_check_version=SVELTE_CHECK_VERSION,
            vite_version=VITE_VERSION,
        )


provider = DenoSvelteProvider()
