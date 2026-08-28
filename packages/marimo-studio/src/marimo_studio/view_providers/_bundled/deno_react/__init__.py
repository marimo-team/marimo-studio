"""Provide React projects as editable Studio views.

The React provider creates a complete TypeScript starter, shows its project
files in Source, identifies cell, output, and value mounts in JSX, and builds
browser files with the pinned Deno toolchain for Studio to validate and
publish.

Inspection records which documents may be edited and which inputs affect a
build. ``deno.lock`` remains read-only. TypeScript and mount diagnostics point
back to authored source, and every mount records the notebook targets that
source location may request.
"""

from __future__ import annotations

from pathlib import PurePosixPath

from marimo_studio.view_providers import (
    BuildRequest,
    BuildResult,
    InspectionRequest,
    ProjectInput,
    ProjectInspection,
    ProviderAvailability,
    ProviderInfo,
    ProviderStarter,
    StarterContext,
    ViewProject,
)
from marimo_studio.view_providers._bundled import _deno
from marimo_studio.view_providers._bundled._deno.project import (
    ProviderProjectSpec,
    starter_files,
)
from marimo_studio.view_providers._bundled.deno_react.build import (
    build_react,
    react_project_diagnostics,
)

PROVIDER_KEY = "marimo-studio/react"
STARTER_KEY = "default"
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
_REQUIRED = ("view.toml",)
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
_TEMPLATE_DOCUMENTS = tuple(
    PurePosixPath(path)
    for path in (
        "AGENTS.md",
        "src/App.tsx",
        "src/marimo-studio.d.ts",
        "src/lib/use-marimo-value.ts",
        "src/main.tsx",
        "src/index.html",
        "src/style.css",
        "deno.json",
        "deno.lock",
    )
)
_PROJECT = ProviderProjectSpec(
    provider_id=PROVIDER_KEY,
    resource_package="marimo_studio.view_providers._bundled.deno_react",
    input_scope=_INPUT_SCOPE,
    document_roots=_DOCUMENT_ROOTS,
    required_files=_REQUIRED,
    editor_languages=_EDITOR_LANGUAGES,
    read_only=frozenset({"deno.lock"}),
    option_paths={
        "entrypoint": "src/index.html",
        "main": "src/main.tsx",
        "config": "deno.json",
        "lockfile": "deno.lock",
    },
    analyzer_suffixes=frozenset({".js", ".jsx", ".mjs", ".ts", ".tsx"}),
    lockfile="deno.lock",
    template_documents=_TEMPLATE_DOCUMENTS,
    build_fingerprint=(
        f"{_deno.DENO_VERSION}:{REACT_VERSION}:{REACT_DOM_VERSION}:"
        f"{TYPESCRIPT_VERSION}:{PROJECTION_CONTRACT_VERSION}:"
        f"{BUILD_CONTRACT_VERSION}"
    ),
)


class DenoReactProvider:
    """Inspect React source and build one immutable browser candidate."""

    info = ProviderInfo(
        title="React",
        summary="Builds a React project with the pinned Deno toolchain.",
        api_version=1,
    )
    _starter = ProviderStarter(
        key=STARTER_KEY,
        title="React",
        summary=(
            "A typed React application with Studio projection elements and a "
            "live-value hook."
        ),
        documents=_TEMPLATE_DOCUMENTS,
    )

    def availability(self, project: ViewProject | None = None) -> ProviderAvailability:
        del project
        return _deno.deno_availability()

    def starters(self) -> tuple[ProviderStarter, ...]:
        return (self._starter,)

    def create(
        self,
        starter: ProviderStarter,
        context: StarterContext,
    ) -> dict[PurePosixPath, bytes]:
        if starter.key != STARTER_KEY:
            raise ValueError(f"Unknown React starter {starter.key!r}")
        return dict(starter_files(_PROJECT, context))

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
