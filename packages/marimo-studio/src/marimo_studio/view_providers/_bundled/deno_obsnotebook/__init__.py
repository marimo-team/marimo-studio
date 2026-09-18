"""Provide Observable Notebook Kit projects through the Studio provider contract."""

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
from marimo_studio.view_providers._bundled._deno.vite_project import build_vite_project
from marimo_studio.view_providers._bundled._starters import (
    create_starter,
    provider_starters,
)
from marimo_studio.view_providers._bundled.deno_obsnotebook.starters import (
    catalog as _STARTERS,
)

PROVIDER_KEY = "marimo-studio/notebook-kit"
NOTEBOOK_KIT_VERSION = "2.6.4"
VITE_VERSION = "8.2.1"
PROJECTION_CONTRACT_VERSION = "notebook-kit-projections-v3"
BUILD_CONTRACT_VERSION = "vite-notebook-kit-artifact-v1"
_INPUT_SCOPE = (
    ProjectInput(PurePosixPath("src"), "directory"),
    ProjectInput(PurePosixPath("view.toml"), "file"),
    ProjectInput(PurePosixPath("package.json"), "file"),
    ProjectInput(PurePosixPath("deno.json"), "file"),
    ProjectInput(PurePosixPath("vite.config.ts"), "file"),
    ProjectInput(PurePosixPath("deno.lock"), "file"),
    ProjectInput(PurePosixPath("public"), "directory"),
)
_DOCUMENT_ROOTS = (PurePosixPath("AGENTS.md"), PurePosixPath("DESIGN.md"))
_REQUIRED = (
    "view.toml",
    "package.json",
)
_EDITOR_LANGUAGES = {
    "AGENTS.md": "markdown",
    "DESIGN.md": "markdown",
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
    provider_id=PROVIDER_KEY,
    analyzer_package="marimo_studio.view_providers._bundled.deno_obsnotebook",
    input_scope=_INPUT_SCOPE,
    document_roots=_DOCUMENT_ROOTS,
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
    build_fingerprint=(
        f"{NOTEBOOK_KIT_VERSION}:{VITE_VERSION}:"
        f"{PROJECTION_CONTRACT_VERSION}:{BUILD_CONTRACT_VERSION}"
    ),
)


class NotebookKitProvider:
    """Inspect Observable notebook HTML and build one immutable Vite candidate."""

    info = ProviderInfo(
        title="Observable Notebook Kit",
        summary="Builds Observable notebook HTML with the installed Deno toolchain.",
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
        return build_vite_project(
            request,
            _PROJECT,
            vite_version=VITE_VERSION,
            label="Notebook Kit provider",
            code_prefix="notebook-kit",
        )


provider = NotebookKitProvider()
