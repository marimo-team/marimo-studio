"""Create a notebook HTML view populated with native Marimo displays."""

from __future__ import annotations

import html
from pathlib import PurePosixPath

from marimo_studio.view_providers import ProviderStarter, StarterContext
from marimo_studio.view_providers._bundled._starters import (
    BundledStarter,
    StarterRendering,
    starter_cells,
)


def _render(context: StarterContext) -> StarterRendering:
    targets = tuple(
        target for cell, target in starter_cells(context) if cell.may_display_output
    )
    return StarterRendering(
        replacements={
            "__NOTEBOOK_CELL_HOSTS_HTML__": "\n".join(
                f'    <marimo-cell name="{html.escape(target.target, quote=True)}"'
                "></marimo-cell>"
                for target in targets
            )
        },
        cell_targets=targets,
    )


starter = BundledStarter(
    info=ProviderStarter(
        key="default",
        title="Observable Notebook Kit",
        summary=(
            "Reactive Observable notebook HTML with native Marimo projections "
            "and a live-value generator."
        ),
        documents=tuple(
            PurePosixPath(path)
            for path in (
                "AGENTS.md",
                "src/index.html",
                "src/page.tmpl",
                "src/style.css",
                "src/lib/marimo-value.js",
                "src/lib/studio-notebook.ts",
                "package.json",
                "deno.json",
                "vite.config.ts",
                "deno.lock",
            )
        ),
    ),
    package=__name__,
    render=_render,
)
