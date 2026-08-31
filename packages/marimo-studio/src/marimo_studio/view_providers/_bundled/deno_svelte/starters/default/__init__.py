"""Define the notebook-populated Svelte application starter."""

from __future__ import annotations

from pathlib import PurePosixPath

from marimo_studio.view_providers import ProviderStarter, StarterContext
from marimo_studio.view_providers._bundled._starters import (
    BundledStarter,
    StarterRendering,
    starter_cells,
    typescript_string_array,
)

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


def _render(context: StarterContext) -> StarterRendering:
    cells = tuple(item for item in starter_cells(context) if item[0].displays_output)
    targets = tuple(target for _cell, target in cells)
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
    return StarterRendering(
        replacements={
            _HOSTS_MARKER: hosts,
        },
        cell_targets=targets,
    )


starter = BundledStarter(
    info=ProviderStarter(
        key="default",
        title="Svelte",
        summary=(
            "A typed Svelte application populated with Studio notebook display "
            "cells and a live-value action."
        ),
        documents=_DOCUMENTS,
    ),
    package=__name__,
    render=_render,
)
