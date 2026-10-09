"""Define the Typst report starter."""

from __future__ import annotations

from pathlib import PurePosixPath

from marimo_studio.view_providers import (
    PackagedStarter,
    ProviderStarter,
    StarterContext,
    StarterMarkers,
)


def _typst_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _markers(context: StarterContext) -> StarterMarkers:
    heading = context.view_name.replace("-", " ").title()
    reads = '#let report = marimo_value("report", default: none)'
    defines_report = any(
        "report" in cell.definitions for cell in context.notebook.cells
    )
    return StarterMarkers(
        values={
            "__NOTEBOOK_LABEL_TYP__": _typst_string(context.notebook_label),
            "__VIEW_HEADING_TYP__": _typst_string(heading),
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
    ),
    package=__name__,
    markers=_markers,
)
