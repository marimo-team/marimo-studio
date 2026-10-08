"""Provide Observable Notebook Kit projects through the Studio provider contract."""

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
from marimo_studio.view_providers._builtin._deno.vite_project import build_vite_project
from marimo_studio.view_providers._builtin.deno_obsnotebook.starters import STARTERS

NOTEBOOK_KIT_VERSION = "2.6.4"
VITE_VERSION = "8.2.1"
_INPUTS = (
    BuildInput(PurePosixPath("src"), "directory"),
    BuildInput(PurePosixPath("package.json"), "file"),
    BuildInput(PurePosixPath("deno.json"), "file"),
    BuildInput(PurePosixPath("vite.config.ts"), "file"),
    BuildInput(PurePosixPath("deno.lock"), "file"),
    BuildInput(PurePosixPath("public"), "directory"),
)
_REQUIRED = ("package.json",)
_EDITOR_LANGUAGES = {
    "deno.json": "json",
    "deno.lock": "json",
    "package.json": "json",
    "vite.config.ts": "typescript",
    ".css": "css",
    ".html": "html",
    ".js": "javascript",
    ".json": "json",
    ".mjs": "javascript",
    ".svg": "xml",
    ".tmpl": "html",
    ".ts": "typescript",
}
_PROJECT = ProviderProjectSpec(
    analyzer_package=__name__,
    inputs=_INPUTS,
    required_files=_REQUIRED,
    editor_languages=_EDITOR_LANGUAGES,
    read_only=frozenset({"deno.lock"}),
    option_paths={
        "entrypoint": "src/index.html",
        "config": "deno.json",
        "lockfile": "deno.lock",
        "vite_config": "vite.config.ts",
    },
    analyzer_suffixes=frozenset({".html", ".tmpl"}),
)


class NotebookKitProvider:
    """Inspect Observable notebook HTML and build one immutable Vite candidate."""

    info = ProviderInfo(
        title="Observable Notebook Kit",
        summary="Builds Observable notebook HTML with the installed Deno toolchain.",
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
        return build_vite_project(
            request,
            _PROJECT,
            vite_version=VITE_VERSION,
            label="Notebook Kit provider",
            code_prefix="notebook-kit",
        )


provider = NotebookKitProvider()
