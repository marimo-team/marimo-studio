"""Define the notebook-populated Svelte application starter."""

from __future__ import annotations

from pathlib import PurePosixPath

from marimo_studio.view_providers import (
    PackagedStarter,
    ProviderStarter,
    StarterContext,
    StarterMarkers,
)
from marimo_studio.view_providers._builtin._deno.starters import typescript_string_array

_HOSTS_MARKER = "__NOTEBOOK_CELL_HOSTS_SVELTE__"
_DOCUMENTS = (
    PurePosixPath("AGENTS.md"),
    PurePosixPath("src/App.svelte"),
    PurePosixPath("src/app.d.ts"),
    PurePosixPath("src/lib/marimo-value.ts"),
    PurePosixPath("src/main.ts"),
    PurePosixPath("src/index.html"),
    PurePosixPath("src/style.css"),
    PurePosixPath("src/vite-env.d.ts"),
    PurePosixPath("package.json"),
    PurePosixPath("deno.json"),
    PurePosixPath("vite.config.ts"),
    PurePosixPath("svelte.config.js"),
    PurePosixPath("tsconfig.json"),
    PurePosixPath("deno.lock"),
)


def _markers(context: StarterContext) -> StarterMarkers:
    targets = context.output_cells
    hosts = (
        "{#each "
        + typescript_string_array(
            tuple(target.target for target in targets),
            indent="      ",
        )
        + " as name}\n"
        + "        <marimo-cell {name}></marimo-cell>\n"
        + "      {/each}"
        if targets
        else ""
    )
    return StarterMarkers(
        values={
            _HOSTS_MARKER: hosts,
        },
        cell_targets=targets,
    )


starter = PackagedStarter(
    info=ProviderStarter(
        key="default",
        title="Svelte",
        summary=(
            "A TypeScript Svelte app with every notebook output in place, plus "
            "an action that reads live notebook values."
        ),
        documents=_DOCUMENTS,
    ),
    package=__name__,
    markers=_markers,
)
