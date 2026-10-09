"""Provide React projects as editable Studio views.

The React provider creates a complete TypeScript starter, shows its project
files in Source, identifies cell, output, and value hosts in JSX, and builds
browser files with the installed Deno toolchain for Studio to validate and
publish.

Inspection records which documents may be edited and which inputs affect a
build. ``deno.lock`` remains read-only. TypeScript and projection diagnostics point
back to authored source, and every site records the notebook targets that
source location may request.
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
from marimo_studio.view_providers._builtin.deno_react.build import (
    build_react,
    react_project_diagnostics,
)
from marimo_studio.view_providers._builtin.deno_react.starters import STARTERS

_INPUTS = (
    BuildInput(PurePosixPath("src"), "directory"),
    BuildInput(PurePosixPath("deno.json"), "file"),
    BuildInput(PurePosixPath("deno.lock"), "file"),
    BuildInput(PurePosixPath("public"), "directory"),
)
_REQUIRED = ("src/index.html",)
_EDITOR_LANGUAGES = {
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
    analyzer_package=__name__,
    inputs=_INPUTS,
    required_files=_REQUIRED,
    editor_languages=_EDITOR_LANGUAGES,
    read_only=frozenset({"deno.lock"}),
    option_paths={
        "main": "src/main.tsx",
        "config": "deno.json",
        "lockfile": "deno.lock",
    },
    analyzer_suffixes=frozenset({".js", ".jsx", ".mjs", ".ts", ".tsx"}),
)


class DenoReactProvider:
    """Inspect React source and build one immutable browser candidate."""

    info = ProviderInfo(
        title="React",
        summary="Builds a React project with the installed Deno toolchain.",
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
        project = request.project
        return _PROJECT.inspect(
            request,
            self.availability(),
            preflight_diagnostics=react_project_diagnostics(project),
        )

    def build(self, request: BuildRequest) -> BuildResult:
        return build_react(request)


provider = DenoReactProvider()
