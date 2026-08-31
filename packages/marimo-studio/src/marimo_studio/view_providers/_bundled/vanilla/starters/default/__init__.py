"""Define the notebook-populated Vanilla document starter."""

from __future__ import annotations

import html
from pathlib import PurePosixPath

from marimo_studio.view_providers import (
    ProviderStarter,
    StarterContext,
)
from marimo_studio.view_providers._bundled._starters import (
    BundledStarter,
    StarterRendering,
    starter_cells,
)

_CELL_MARKER = "__NOTEBOOK_CELLS_HTML__"


def _render(context: StarterContext) -> StarterRendering:
    cells = tuple(item for item in starter_cells(context) if item[0].displays_output)
    markup = "".join(
        '\n        <marimo-cell name="'
        + html.escape(target.target, quote=True)
        + '"></marimo-cell>'
        for _cell, target in cells
    )
    if markup:
        markup += "\n      "
    return StarterRendering(
        replacements={_CELL_MARKER: markup},
        cell_targets=tuple(target for _cell, target in cells),
    )


starter = BundledStarter(
    info=ProviderStarter(
        key="default",
        title="HTML document",
        summary=(
            "One editable HTML file populated with Studio notebook display "
            "cells and an inline live-value adapter."
        ),
        documents=(PurePosixPath("index.html"), PurePosixPath("AGENTS.md")),
    ),
    package=__name__,
    render=_render,
)
