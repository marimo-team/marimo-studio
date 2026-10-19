"""Define the Typst report starter."""

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


def _typst_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _markers(context: StarterContext) -> StarterMarkers:
    reads = '#let report = marimo_value("report", default: none)'
    defines_report = any(
        "report" in cell.definitions for cell in context.notebook.cells
    )
    return StarterMarkers(
        values={
            "__NOTEBOOK_LABEL_TYP__": _typst_string(context.notebook_label),
            "__VIEW_TITLE_TYP__": _typst_string(context.title),
            "__PAPER_TYP__": _typst_string(str(context.settings["paper"])),
            "__REPORT_BINDING_TYP__": (
                reads
                if defines_report
                else "// Define `report` in the notebook, then replace the next "
                f"line with:\n// {reads}\n#let report = none"
            ),
        },
        cell_targets=(),
    )


starter = PackagedStarter(
    info=ProviderStarter(
        key="default",
        title="Typst report",
        summary=(
            "A paged PDF report in Typst that lays out a notebook value and "
            "re-renders when the notebook changes."
        ),
        documents=(
            PurePosixPath("main.typ"),
            PurePosixPath("marimo.typ"),
            PurePosixPath("AGENTS.md"),
        ),
        homepage="https://typst.app",
        settings=(
            StarterSetting(
                key="paper",
                label="Paper size",
                help="The page size of the PDF. main.typ sets it in its page rule.",
                default="a4",
                choices=(
                    SettingChoice("a4", "A4"),
                    SettingChoice("us-letter", "US Letter"),
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
