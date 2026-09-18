"""Provide React projects as editable Studio views.

The React provider creates a complete TypeScript starter, shows its project
files in Source, identifies cell, output, and value mounts in JSX, and builds
browser files with the installed Deno toolchain for Studio to validate and
publish.

Inspection records which documents may be edited and which inputs affect a
build. ``deno.lock`` remains read-only. TypeScript and mount diagnostics point
back to authored source, and every mount records the notebook targets that
source location may request.
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
from marimo_studio.view_providers._bundled.deno_react.build import (
    build_react,
    react_project_diagnostics,
)
from marimo_studio.view_providers._bundled.deno_react.starters import (
    catalog as _STARTERS,
)

PROVIDER_KEY = "marimo-studio/react"
REACT_VERSION = "19.2.4"
REACT_DOM_VERSION = "19.2.4"
TYPESCRIPT_VERSION = "6.0.3"
PROJECTION_CONTRACT_VERSION = "jsx-projections-v2"
BUILD_CONTRACT_VERSION = "deno-html-artifact-v1"
_INPUT_SCOPE = (
    ProjectInput(PurePosixPath("src"), "directory"),
    ProjectInput(PurePosixPath("view.toml"), "file"),
    ProjectInput(PurePosixPath("deno.json"), "file"),
    ProjectInput(PurePosixPath("deno.lock"), "file"),
    ProjectInput(PurePosixPath("public"), "directory"),
)
_DOCUMENT_ROOTS = (PurePosixPath("AGENTS.md"), PurePosixPath("DESIGN.md"))
_REQUIRED = ("view.toml", "src/index.html")
_EDITOR_LANGUAGES = {
    "AGENTS.md": "markdown",
    "DESIGN.md": "markdown",
    "deno.json": "json",
    "deno.lock": "json",
    ".css": "css",
    ".html": "html",
    ".js": "javascript",
    ".json": "json",
    ".jsx": "javascriptreact",
    ".mjs": "javascript",
    ".svg": "xml",
    ".ts": "typescript",
    ".tsx": "typescriptreact",
}
_PROJECT = ProviderProjectSpec(
    provider_id=PROVIDER_KEY,
    analyzer_package="marimo_studio.view_providers._bundled.deno_react",
    input_scope=_INPUT_SCOPE,
    document_roots=_DOCUMENT_ROOTS,
    required_files=_REQUIRED,
    editor_languages=_EDITOR_LANGUAGES,
    read_only=frozenset({"deno.lock"}),
    option_paths={
        "main": "src/main.tsx",
        "config": "deno.json",
        "lockfile": "deno.lock",
    },
    analyzer_suffixes=frozenset({".js", ".jsx", ".mjs", ".ts", ".tsx"}),
    build_fingerprint=(
        f"{REACT_VERSION}:{REACT_DOM_VERSION}:"
        f"{TYPESCRIPT_VERSION}:{PROJECTION_CONTRACT_VERSION}:"
        f"{BUILD_CONTRACT_VERSION}"
    ),
)


class DenoReactProvider:
    """Inspect React source and build one immutable browser candidate."""

    info = ProviderInfo(
        title="React",
        summary="Builds a React project with the installed Deno toolchain.",
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
        project = request.project
        return _PROJECT.inspect(
            request,
            self.availability(project),
            preflight_diagnostics=react_project_diagnostics(project),
        )

    def build(self, request: BuildRequest) -> BuildResult:
        return build_react(request, _PROJECT)


provider = DenoReactProvider()
