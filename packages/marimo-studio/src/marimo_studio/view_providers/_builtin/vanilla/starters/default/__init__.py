"""Define the notebook-populated Vanilla document starter."""

from __future__ import annotations

import html
from pathlib import PurePosixPath

from marimo_studio.view_providers import (
    PackagedStarter,
    ProviderStarter,
    StarterContext,
    StarterMarkers,
)

_CELL_MARKER = "__NOTEBOOK_CELLS_HTML__"


def _markers(context: StarterContext) -> StarterMarkers:
    targets = context.output_cells
    markup = "".join(
        '\n        <marimo-cell name="'
        + html.escape(target.target, quote=True)
        + '"></marimo-cell>'
        for target in targets
    )
    if markup:
        markup += "\n      "
    return StarterMarkers(
        values={_CELL_MARKER: markup},
        cell_targets=targets,
    )


starter = PackagedStarter(
    info=ProviderStarter(
        key="default",
        title="HTML document",
        summary=(
            "A single HTML file with every notebook output in place, utility "
            "CSS, icons, and a helper that reads live notebook values."
        ),
        documents=(PurePosixPath("index.html"), PurePosixPath("AGENTS.md")),
    ),
    package=__name__,
    markers=_markers,
)
