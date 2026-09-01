"""Define the notebook-populated Reveal.js deck starter."""

from __future__ import annotations

import json
import re
from pathlib import PurePosixPath

from marimo_studio.view_providers import (
    CellSpec,
    ProviderStarter,
    StarterCellTarget,
    StarterContext,
)
from marimo_studio.view_providers._bundled._starters import (
    BundledStarter,
    StarterRendering,
    starter_cells,
)

_SLIDE_HOSTS_MARKER = "__NOTEBOOK_SLIDE_HOSTS_TSX__"
_TITLE_MARKER = "__NOTEBOOK_TITLE_JSON__"
_ATX_HEADING = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.*?)[ \t]*$")
_SETEXT_HEADING = re.compile(r"^ {0,3}(=+|-+)[ \t]*$")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_CLOSING_HASHES = re.compile(r"[ \t]+#+[ \t]*$")
_INLINE_LINK = re.compile(r"!?\[([^\]]+)\]\([^)]*\)")
_CODE_SPAN = re.compile(r"`+([^`]+?)`+")
_INLINE_MARKERS = (
    re.compile(r"\*\*(.+?)\*\*"),
    re.compile(r"__(.+?)__"),
    re.compile(r"~~(.+?)~~"),
    re.compile(r"(?<!\*)\*([^*]+?)\*(?!\*)"),
    re.compile(r"(?<!_)_([^_]+?)_(?!_)"),
)
_ESCAPED_PUNCTUATION = re.compile(r"\\([\\`*{}\[\]()#+\-.!_>~|])")
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


def _heading_text(source: str) -> str:
    text = _CLOSING_HASHES.sub("", source)
    text = _INLINE_LINK.sub(r"\1", text)
    text = _CODE_SPAN.sub(r"\1", text)
    for marker in _INLINE_MARKERS:
        text = marker.sub(r"\1", text)
    return _ESCAPED_PUNCTUATION.sub(r"\1", text).strip()


def _markdown_headings(markdown: str | None) -> tuple[tuple[int, str], ...]:
    if markdown is None:
        return ()
    headings: list[tuple[int, str]] = []
    lines = markdown.splitlines()
    fence: tuple[str, int] | None = None
    for index, line in enumerate(lines):
        fence_match = _FENCE.match(line)
        if fence_match is not None:
            marker = fence_match.group(1)
            if fence is None:
                fence = (marker[0], len(marker))
            elif (
                marker[0] == fence[0]
                and len(marker) >= fence[1]
                and not fence_match.group(2).strip()
            ):
                fence = None
            continue
        if fence is not None:
            continue
        match = _ATX_HEADING.match(line)
        if match is not None:
            text = _heading_text(match.group(2))
            if text:
                headings.append((len(match.group(1)), text))
            continue
        if (
            index > 0
            and lines[index - 1].strip()
            and (setext := _SETEXT_HEADING.match(line)) is not None
        ):
            level = 1 if setext.group(1).startswith("=") else 2
            text = _heading_text(lines[index - 1].strip())
            if text:
                headings.append((level, text))
    return tuple(headings)


def _humanize(value: str) -> str:
    return " ".join(value.replace("_", " ").replace("-", " ").split()).title()


def _notebook_title(
    context: StarterContext,
    cells: tuple[tuple[CellSpec, StarterCellTarget], ...],
) -> str:
    configured = context.notebook.app_config.get("app_title")
    if isinstance(configured, str) and configured.strip():
        return configured.strip()
    for cell, _target in cells:
        heading = next(
            (text for level, text in _markdown_headings(cell.markdown) if level == 1),
            None,
        )
        if heading is not None:
            return heading
    return _humanize(context.notebook_name)


def _slide_title(cell: CellSpec) -> tuple[str, bool]:
    heading = next(iter(_markdown_headings(cell.markdown)), None)
    if heading is not None:
        return heading[1], False
    if cell.name is not None:
        return _humanize(cell.name), True
    return f"Cell {cell.index + 1}", True


def _typescript_slides(
    cells: tuple[tuple[CellSpec, StarterCellTarget], ...],
    *,
    indent: str = "",
) -> str:
    lines = ["["]
    for cell, target in cells:
        title, show_title = _slide_title(cell)
        target_source = json.dumps(target.target, ensure_ascii=False)
        title_source = json.dumps(title, ensure_ascii=False)
        lines.extend(
            (
                f"{indent}  {{",
                f'{indent}    "target": {target_source},',
                f'{indent}    "title": {title_source},',
                f'{indent}    "showTitle": {str(show_title).lower()},',
                f"{indent}  }},",
            )
        )
    lines.append(f"{indent}]")
    return "\n".join(lines)


def _render(context: StarterContext) -> StarterRendering:
    cells = tuple(item for item in starter_cells(context) if item[0].may_display_output)
    hosts = (
        "{"
        + _typescript_slides(cells, indent="    ")
        + ".map(({ target, title, showTitle }) => (\n"
        + "      <Slide key={target}>\n"
        + "        {showTitle ? <h2>{title}</h2> : null}\n"
        + "        <marimo-cell name={target} />\n"
        + "      </Slide>\n"
        + "    ))}"
        if cells
        else ""
    )
    return StarterRendering(
        replacements={
            _SLIDE_HOSTS_MARKER: hosts,
            _TITLE_MARKER: json.dumps(
                _notebook_title(context, cells),
                ensure_ascii=False,
            ),
        },
        cell_targets=tuple(target for _cell, target in cells),
    )


starter = BundledStarter(
    info=ProviderStarter(
        key="reveal",
        title="Reveal.js slides",
        summary=(
            "A React slide deck populated with one enabled notebook cell that may "
            "display output per slide."
        ),
        documents=_DOCUMENTS,
    ),
    package=__name__,
    render=_render,
)
