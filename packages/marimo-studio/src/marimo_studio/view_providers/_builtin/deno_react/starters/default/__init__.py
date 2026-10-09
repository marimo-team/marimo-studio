"""Define the notebook-populated React application starter."""

from __future__ import annotations

from pathlib import PurePosixPath

from marimo_studio.view_providers import (
    PackagedStarter,
    ProviderStarter,
    StarterContext,
    StarterMarkers,
)
from marimo_studio.view_providers._builtin._deno.starters import typescript_string_array

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


def _markers(context: StarterContext) -> StarterMarkers:
    targets = context.output_cells
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
    return StarterMarkers(
        values={
            _HOSTS_MARKER: hosts,
        },
        cell_targets=targets,
    )


starter = PackagedStarter(
    info=ProviderStarter(
        key="default",
        title="React",
        summary=(
            "A TypeScript React app with every notebook output in place, plus a "
            "hook that reads live notebook values."
        ),
        documents=_DOCUMENTS,
    ),
    package=__name__,
    markers=_markers,
)
