"""Define the LaTeX article starter."""

from __future__ import annotations

from importlib import resources
from pathlib import PurePosixPath

from marimo_studio.view_providers import (
    PackagedStarter,
    ProviderStarter,
    SettingChoice,
    StarterContext,
    StarterMarkers,
    StarterSetting,
)
from marimo_studio.view_providers._builtin.latex._inputs import latex_text


def _markers(context: StarterContext) -> StarterMarkers:
    return StarterMarkers(
        values={
            "__NOTEBOOK_LABEL_TEX__": latex_text(context.notebook_label),
            "__VIEW_TITLE_TEX__": latex_text(context.title),
            "__PAPER_TEX__": str(context.settings["paper"]),
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
        homepage="https://www.latex-project.org",
        settings=(
            StarterSetting(
                key="paper",
                label="Paper size",
                help=(
                    "The page size of the PDF. main.tex passes it to the "
                    "geometry package."
                ),
                default="a4paper",
                choices=(
                    SettingChoice("a4paper", "A4"),
                    SettingChoice("letterpaper", "US Letter"),
                ),
            ),
        ),
        format="PDF",
        icon=resources.files(__name__).joinpath("icon.svg").read_text("utf-8"),
        preview=resources.files(__name__).joinpath("preview.webp").read_bytes(),
    ),
    package=__name__,
    markers=_markers,
)
