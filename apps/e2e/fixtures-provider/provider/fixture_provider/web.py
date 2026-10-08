"""Build the multi-document web project used by Studio E2E."""

from __future__ import annotations

from pathlib import PurePosixPath

from marimo_studio.view_providers import (
    BuildInput,
    BuildRequest,
    BuildResult,
    InspectionRequest,
    ProjectInspection,
    ProviderAvailability,
    ProviderError,
    ProviderInfo,
    ProviderStarter,
    SourceDocument,
    StarterContext,
    StarterPlan,
    copy_inputs,
    html_sites,
)

_ENTRY = PurePosixPath("src/index.html")
_DOCUMENTS = (
    _ENTRY,
    PurePosixPath("src/app.css"),
    PurePosixPath("src/scripts/app.js"),
    PurePosixPath("src/scripts/message.js"),
)
_LANGUAGES = {".html": "html", ".css": "css", ".js": "javascript"}


class MultiFileProvider:
    info = ProviderInfo(
        title="E2E web project",
        summary="Builds one HTML entry and its declared browser assets.",
        options=frozenset({"entrypoint"}),
    )
    _starter = ProviderStarter(
        key="default",
        title="E2E web project",
        summary="HTML, CSS, and JavaScript source documents.",
        documents=_DOCUMENTS,
    )

    def availability(self) -> ProviderAvailability:
        return ProviderAvailability(True, version="1.0.0")

    def starters(self) -> tuple[ProviderStarter, ...]:
        return (self._starter,)

    def create(
        self,
        starter: ProviderStarter,
        context: StarterContext,
    ) -> StarterPlan:
        if starter != self._starter:
            raise ValueError(f"Unknown starter {starter.key!r}")
        del context
        return StarterPlan(
            files={
                _ENTRY: (
                    b'<!doctype html><html lang="en"><head><meta charset="utf-8">'
                    b'<meta name="viewport" content="width=device-width, initial-scale=1">'
                    b'<link rel="stylesheet" href="app.css"></head><body>'
                    b'<main id="app-shell"><h1 data-web-heading>External web project</h1>'
                    b"<p data-web-script>Waiting for JavaScript</p>"
                    b'<p>Notebook metric: <strong data-web-value mo-value="metric"></strong></p>'
                    b'</main><script type="module" src="scripts/app.js"></script></body></html>'
                ),
                PurePosixPath("src/app.css"): (
                    b"body { margin: 0; background: rgb(238, 244, 240); }\n"
                    b"[data-web-heading] { color: rgb(24, 78, 55); }\n"
                ),
                PurePosixPath("src/scripts/app.js"): (
                    b'import { message } from "./message.js";\n'
                    b'const target = document.querySelector("[data-web-script]");\n'
                    b'if (!(target instanceof HTMLElement)) throw new Error("Web marker missing");\n'
                    b"target.textContent = message;\n"
                ),
                PurePosixPath(
                    "src/scripts/message.js"
                ): b'export const message = "Imported module ready";\n',
            },
            cell_targets=(),
        )

    def inspect(self, request: InspectionRequest) -> ProjectInspection:
        project = request.project
        entry = project.path_option(
            "entrypoint", default=_ENTRY.as_posix(), suffix=".html"
        )
        documents = tuple(
            path
            for path in (entry, *_DOCUMENTS[1:])
            if project.root.joinpath(*path.parts).is_file()
        )
        if entry not in documents:
            raise ProviderError(
                f"Web project entry is unavailable: {entry}",
                code="project-document-missing",
            )
        sites, diagnostics = html_sites(
            entry, project.root.joinpath(*entry.parts).read_bytes()
        )
        return ProjectInspection(
            documents=tuple(
                SourceDocument(path, _LANGUAGES[path.suffix], "edit")
                for path in documents
            ),
            inputs=tuple(BuildInput(path, "file") for path in documents),
            sites=sites,
            diagnostics=diagnostics,
        )

    def build(self, request: BuildRequest) -> BuildResult:
        copy_inputs(request, request.staging_root)
        return BuildResult(
            request.project.path_option("entrypoint", default=_ENTRY.as_posix())
        )


multi_provider = MultiFileProvider()
