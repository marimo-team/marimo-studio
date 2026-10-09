"""Define the LaTeX article starter."""

from __future__ import annotations

from pathlib import PurePosixPath

from marimo_studio.view_providers import (
    PackagedStarter,
    ProviderStarter,
    StarterContext,
    StarterMarkers,
)
from marimo_studio.view_providers._builtin.latex._inputs import latex_text


def _markers(context: StarterContext) -> StarterMarkers:
    return StarterMarkers(
        values={
            "__NOTEBOOK_LABEL_TEX__": latex_text(context.notebook_label),
            "__VIEW_HEADING_TEX__": latex_text(
                context.view_name.replace("-", " ").title()
            ),
        },
        cell_targets=(),
    )


starter = PackagedStarter(
    info=ProviderStarter(
        key="default",
        title="LaTeX article",
        summary=(
            "A LaTeX article typeset to PDF that places notebook values and "
            "figures and renders again when the notebook changes."
        ),
        documents=(
            PurePosixPath("main.tex"),
            PurePosixPath("marimo.sty"),
            PurePosixPath("AGENTS.md"),
        ),
    ),
    package=__name__,
    markers=_markers,
)
