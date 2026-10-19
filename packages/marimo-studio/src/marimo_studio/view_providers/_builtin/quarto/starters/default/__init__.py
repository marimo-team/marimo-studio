"""Define the notebook-populated Quarto document starter."""

from __future__ import annotations

from importlib import resources
from pathlib import PurePosixPath

from marimo_studio.view_providers import (
    PackagedStarter,
    ProviderStarter,
    StarterContext,
    StarterMarkers,
    StarterSetting,
)


def _markers(context: StarterContext) -> StarterMarkers:
    targets = context.output_cells
    return StarterMarkers(
        values={
            "__TOC_QMD__": "true" if context.settings["toc"] else "false",
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
        homepage="https://quarto.org",
        settings=(
            StarterSetting(
                key="toc",
                label="Table of contents",
                help=(
                    "Lists the document's headings beside its text. The toc "
                    "field in index.qmd turns it on or off later."
                ),
                default=False,
            ),
        ),
        format="Document",
        icon=resources.files(__name__).joinpath("icon.svg").read_text("utf-8"),
        preview=resources.files(__name__).joinpath("preview.webp").read_bytes(),
    ),
    package=__name__,
    markers=_markers,
)
