"""Define the notebook-populated Quarto document starter."""

from __future__ import annotations

from pathlib import PurePosixPath

from marimo_studio.view_providers import (
    PackagedStarter,
    ProviderStarter,
    StarterContext,
    StarterMarkers,
)


def _markers(context: StarterContext) -> StarterMarkers:
    targets = context.output_cells
    return StarterMarkers(
        values={
            "__NOTEBOOK_CELLS_QMD__": "\n\n".join(
                f'{{{{< marimo cell="{target.target}" >}}}}' for target in targets
            ),
        },
        cell_targets=targets,
    )


starter = PackagedStarter(
    info=ProviderStarter(
        key="default",
        title="Quarto document",
        summary=(
            "A Quarto document with every notebook output in place, rendered "
            "with Quarto's typography, callouts, and layout."
        ),
        documents=(PurePosixPath("index.qmd"), PurePosixPath("AGENTS.md")),
    ),
    package=__name__,
    markers=_markers,
)
