"""Provide Svelte projects as editable Studio views.

The Svelte provider creates a complete TypeScript and Vite starter, shows
component and configuration files in Source, identifies cell, output, and value
hosts in Svelte templates, and builds browser files with the installed Deno
toolchain for Studio to validate and publish.

Inspection records which documents may be edited and which inputs affect a
build. ``deno.lock`` and ``src/vite-env.d.ts`` remain read-only. Svelte,
TypeScript, and projection diagnostics point back to authored source, and every
site records the notebook targets that source location may request.
"""

from __future__ import annotations

from pathlib import PurePosixPath

from marimo_studio.view_providers import (
    BuildInput,
    BuildRequest,
    BuildResult,
    InspectionRequest,
    ProjectInspection,
    ProviderAvailability,
    ProviderInfo,
    ProviderStarter,
    StarterContext,
    StarterPlan,
    create_starter,
)
from marimo_studio.view_providers._builtin import _deno
from marimo_studio.view_providers._builtin._deno.project import ProviderProjectSpec
from marimo_studio.view_providers._builtin.deno_svelte.build import build_svelte
from marimo_studio.view_providers._builtin.deno_svelte.starters import STARTERS

SVELTE_CHECK_VERSION = "4.7.5"
VITE_VERSION = "8.2.1"
_INPUTS = (
    BuildInput(PurePosixPath("src"), "directory"),
    BuildInput(PurePosixPath("package.json"), "file"),
    BuildInput(PurePosixPath("deno.json"), "file"),
    BuildInput(PurePosixPath("vite.config.ts"), "file"),
    BuildInput(PurePosixPath("svelte.config.js"), "file"),
    BuildInput(PurePosixPath("tsconfig.json"), "file"),
    BuildInput(PurePosixPath("deno.lock"), "file"),
    BuildInput(PurePosixPath("public"), "directory"),
)
_REQUIRED = (
    "package.json",
    "svelte.config.js",
)
_EDITOR_LANGUAGES = {
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
    analyzer_package=__name__,
    inputs=_INPUTS,
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
)


class DenoSvelteProvider:
    """Inspect Svelte source and build one immutable Vite candidate."""

    info = ProviderInfo(
        title="Svelte",
        summary="Builds a Svelte project with the installed Deno toolchain.",
        options=_PROJECT.options,
    )

    def availability(self) -> ProviderAvailability:
        return _deno.deno_availability()

    def starters(self) -> tuple[ProviderStarter, ...]:
        return tuple(starter.info for starter in STARTERS)

    def create(
        self,
        starter: ProviderStarter,
        context: StarterContext,
    ) -> StarterPlan:
        return create_starter(STARTERS, starter, context)

    def inspect(self, request: InspectionRequest) -> ProjectInspection:
        return _PROJECT.inspect(request, self.availability())

    def build(self, request: BuildRequest) -> BuildResult:
        return build_svelte(
            request,
            _PROJECT,
            svelte_check_version=SVELTE_CHECK_VERSION,
            vite_version=VITE_VERSION,
        )


provider = DenoSvelteProvider()
