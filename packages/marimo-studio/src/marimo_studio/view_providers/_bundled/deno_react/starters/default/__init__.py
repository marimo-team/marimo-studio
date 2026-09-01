"""Define the notebook-populated React application starter."""

from __future__ import annotations

from pathlib import PurePosixPath

from marimo_studio.view_providers import ProviderStarter, StarterContext
from marimo_studio.view_providers._bundled._starters import (
    BundledStarter,
    StarterRendering,
    starter_cells,
    typescript_string_array,
)

_HOSTS_MARKER = "__NOTEBOOK_CELL_HOSTS_TSX__"
_DOCUMENTS = (
    PurePosixPath("AGENTS.md"),
    PurePosixPath("src/App.tsx"),
    PurePosixPath("src/marimo-studio.d.ts"),
    PurePosixPath("src/lib/use-marimo-value.ts"),
    PurePosixPath("src/main.tsx"),
    PurePosixPath("src/index.html"),
    PurePosixPath("src/style.css"),
    PurePosixPath("deno.json"),
    PurePosixPath("deno.lock"),
)


def _render(context: StarterContext) -> StarterRendering:
    cells = tuple(item for item in starter_cells(context) if item[0].may_display_output)
    targets = tuple(target for _cell, target in cells)
    hosts = (
        "{"
        + typescript_string_array(
            tuple(target.target for target in targets),
            indent="      ",
        )
        + ".map((name) => <marimo-cell key={name} name={name} />)}"
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
        title="React",
        summary=(
            "A typed React application populated with notebook cells that may "
            "display output and a live-value hook."
        ),
        documents=_DOCUMENTS,
    ),
    package=__name__,
    render=_render,
)
