"""Find projection hosts and includes in Quarto Markdown.

Authors place notebook results with the ``marimo`` shortcode, such as
``{{< marimo cell="summary" >}}``, or with raw HTML hosts. Pandoc passes raw
HTML through to the rendered page, except inside front matter, fenced and
indented code, inline code, math, other shortcodes, and after a backslash
escape. Quarto expands shortcodes outside code and math. Those regions are
masked before each scan. Masking keeps every character's UTF-8 width, so the
scanner's lines, columns, and byte offsets stay exact for the authored file.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from marimo_studio.view_providers import (
    ProjectDiagnostic,
    ProjectionKind,
    ProjectionSite,
    SourceLocation,
    html_sites,
    parse_accept,
)

_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_RAW_HTML_FENCE = re.compile(r"^\s*\{=html\}\s*$")
_SHORTCODE = re.compile(r"\{\{<.*?>\}\}", re.DOTALL)
# One unescaped shortcode on a line. Quarto escapes a shortcode with a third
# brace or a ``/* */`` comment, and both forms render literally.
_SHORTCODE_CALL = re.compile(
    r"(?<!\{)\{\{<\s+(?!/\*)(?P<body>[^\n]*?)(?P<space>\s+)>\}\}(?!\})"
)
_SHORTCODE_PARAM = re.compile(
    r"""(?P<key>[A-Za-z0-9_-]+)=(?P<value>"[^"]*"|'[^']*'|[^"'\s]+)|(?P<bare>"[^"]*"|'[^']*'|[^"'\s]+)"""
)
_HOST_KINDS: tuple[ProjectionKind, ...] = ("cell", "output", "value")
_SITE_ATTRIBUTE = "data-marimo-studio-site"
_DISPLAY_MATH = re.compile(r"(?<!\\)\$\$.*?(?<!\\)\$\$", re.DOTALL)
_INLINE_MATH = re.compile(r"(?<![\\$])\$(?=[^\s$])(?:\\.|[^$\\\n])*?(?<=\S)\$(?!\d)")
_FRONT_MATTER_END = re.compile(r"^(?:---|\.\.\.)\s*$")
_INDENTED = re.compile(r"^(?: {4}|\t)")
_LIST_ITEM = re.compile(r"^ {0,3}(?:[-*+]|\d+[.)])\s")
_ESCAPED_TAG = re.compile(r"(?<!\\)(?:\\\\)*\\<")
_PLACEHOLDERS = {2: "é", 3: "€", 4: "😀"}


def _mask(characters: list[str], start: int, end: int) -> None:
    for index in range(start, end):
        character = characters[index]
        if character in "\r\n":
            continue
        width = len(character.encode("utf-8"))
        characters[index] = " " if width == 1 else _PLACEHOLDERS[width]


def _line_spans(text: str) -> list[tuple[int, int, str]]:
    spans: list[tuple[int, int, str]] = []
    start = 0
    for line in text.splitlines(keepends=True):
        end = start + len(line)
        spans.append((start, end, line.rstrip("\r\n")))
        start = end
    return spans


def _block_regions(text: str) -> list[tuple[int, int]]:
    lines = _line_spans(text)
    regions: list[tuple[int, int]] = []
    index = 0
    if lines and lines[0][2].rstrip() == "---":
        for closing in range(1, len(lines)):
            if _FRONT_MATTER_END.match(lines[closing][2]):
                regions.append((lines[0][0], lines[closing][1]))
                index = closing + 1
                break
    in_list = False
    previous_blank = True
    while index < len(lines):
        start, _end, line = lines[index]
        blank = not line.strip()
        if (
            not blank
            and previous_blank
            and not in_list
            and _INDENTED.match(line) is not None
        ):
            while index < len(lines) and (
                not lines[index][2].strip() or _INDENTED.match(lines[index][2])
            ):
                index += 1
            regions.append((start, lines[index - 1][1]))
            previous_blank = True
            continue
        if not blank and _INDENTED.match(line) is None:
            in_list = _LIST_ITEM.match(line) is not None or (
                in_list and not previous_blank
            )
        previous_blank = blank
        opening = _FENCE.match(line)
        if opening is None:
            index += 1
            continue
        fence, info = opening.groups()
        closing_fence = re.compile(
            rf"^ {{0,3}}{re.escape(fence[0])}{{{len(fence)},}}\s*$"
        )
        closing = next(
            (
                position
                for position in range(index + 1, len(lines))
                if closing_fence.match(lines[position][2])
            ),
            len(lines) - 1,
        )
        if _RAW_HTML_FENCE.match(info) is None:
            regions.append((start, lines[closing][1]))
        else:
            regions.extend(((lines[index][0], lines[index][1]), lines[closing][:2]))
        index = closing + 1
    return regions


def _inline_code_regions(
    text: str,
    blocks: list[tuple[int, int]],
) -> list[tuple[int, int]]:
    regions: list[tuple[int, int]] = []
    pending = sorted(blocks)
    index = 0
    while index < len(text):
        while pending and pending[0][1] <= index:
            pending.pop(0)
        if pending and pending[0][0] <= index:
            index = pending[0][1]
            continue
        if text[index] != "`":
            index += 1
            continue
        run = index
        while run < len(text) and text[run] == "`":
            run += 1
        ticks = text[index:run]
        closing = re.compile(rf"(?<!`){ticks}(?!`)").search(text, run)
        if closing is None:
            index = run
            continue
        if not text.startswith("{=html}", closing.end()):
            regions.append((index, closing.end()))
        index = closing.end()
    return regions


def _masked(text: str, *, shortcodes: bool) -> str:
    """Return text with regions Pandoc keeps out of the page replaced by filler."""
    characters = list(text)
    blocks = _block_regions(text)
    regions = [*blocks, *_inline_code_regions(text, blocks)]
    patterns = (_DISPLAY_MATH, _INLINE_MATH, _ESCAPED_TAG)
    for pattern in (_SHORTCODE, *patterns) if shortcodes else patterns:
        regions.extend(
            match.span()
            for match in pattern.finditer(text)
            if not any(start <= match.start() < end for start, end in regions)
        )
    for start, end in regions:
        _mask(characters, start, end)
    return "".join(characters)


def _decoded(path: PurePosixPath, source: bytes) -> str | ProjectDiagnostic:
    try:
        return source.decode("utf-8")
    except UnicodeDecodeError:
        return ProjectDiagnostic(
            code="source-document-invalid",
            severity="error",
            message=f"{path} must be UTF-8 text.",
            source=SourceLocation(path, 1, 1),
        )


def _position(text: str, index: int) -> tuple[int, int]:
    line = text.count("\n", 0, index) + 1
    return line, index - (text.rfind("\n", 0, index) + 1) + 1


def _unquoted(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _shortcodes(
    text: str,
) -> list[tuple[re.Match[str], str, list[str], dict[str, str]]]:
    """Return each shortcode in the unmasked text with its name and parameters."""
    found = []
    for match in _SHORTCODE_CALL.finditer(_masked(text, shortcodes=False)):
        body = text[match.start("body") : match.end("body")]
        tokens = list(_SHORTCODE_PARAM.finditer(body))
        if not tokens or tokens[0].group("bare") is None:
            continue
        name = _unquoted(tokens[0].group("bare"))
        bare = [
            _unquoted(token.group("bare"))
            for token in tokens[1:]
            if token.group("bare")
        ]
        named = {
            token.group("key"): _unquoted(token.group("value"))
            for token in tokens[1:]
            if token.group("key")
        }
        found.append((match, name, bare, named))
    return found


def include_targets(text: str) -> list[tuple[str, int, int]]:
    """Return each ``{{< include >}}`` directive's target, line, and column.

    Quarto expands an include that stands alone on its line before Pandoc reads
    the document.
    """
    targets = []
    for match, name, bare, _named in _shortcodes(text):
        line_start = text.rfind("\n", 0, match.start()) + 1
        line_end = text.find("\n", match.end())
        line = text[line_start : len(text) if line_end == -1 else line_end]
        if name.casefold() == "include" and bare and line.strip() == match.group(0):
            targets.append((bare[0], *_position(text, match.start())))
    return targets


def _standalone(text: str, match: re.Match[str]) -> bool:
    """Return whether a shortcode is a paragraph of its own, as Quarto requires
    for a block result."""
    lines = text.split("\n")
    line_number = text.count("\n", 0, match.start())
    if lines[line_number].strip() != match.group(0):
        return False
    neighbors = (line_number - 1, line_number + 1)
    return all(
        index < 0 or index >= len(lines) or not lines[index].strip()
        for index in neighbors
    )


def _shortcode_sites(
    path: PurePosixPath,
    text: str,
) -> tuple[list[ProjectionSite], list[ProjectDiagnostic]]:
    sites: list[ProjectionSite] = []
    diagnostics: list[ProjectDiagnostic] = []
    for match, name, _bare, named in _shortcodes(text):
        if name != "marimo":
            continue
        line, column = _position(text, match.start())
        source = SourceLocation(path, line, column)
        kinds: list[ProjectionKind] = [kind for kind in _HOST_KINDS if kind in named]
        if _SITE_ATTRIBUTE in named:
            diagnostics.append(
                ProjectDiagnostic(
                    "projection-site-reserved",
                    "error",
                    f"{_SITE_ATTRIBUTE} is reserved for Studio.",
                    f"Remove {_SITE_ATTRIBUTE}. Studio adds it to built hosts.",
                    source,
                )
            )
            continue
        if len(kinds) != 1:
            diagnostics.append(
                ProjectDiagnostic(
                    "projection-target-missing"
                    if not kinds
                    else "projection-kind-conflict",
                    "error",
                    "The marimo shortcode needs exactly one of cell, output, or value.",
                    'Write {{< marimo cell="summary" >}}, '
                    '{{< marimo output="chart" >}}, or '
                    '{{< marimo value="metrics.total" >}}.',
                    source,
                )
            )
            continue
        kind = kinds[0]
        if kind != "value" and not _standalone(text, match):
            diagnostics.append(
                ProjectDiagnostic(
                    "projection-host-inline",
                    "error",
                    f"A marimo {kind} shortcode must be a paragraph of its own.",
                    "Put the shortcode on its own line with a blank line before and "
                    "after it.",
                    source,
                )
            )
            continue
        try:
            accept = parse_accept(kind, named.get("accept"))
        except ValueError as error:
            diagnostics.append(
                ProjectDiagnostic(
                    "projection-accept-invalid",
                    "error",
                    f"The marimo shortcode accept is invalid: {error}.",
                    'Write {{< marimo output="chart" accept="image/svg+xml" >}}.',
                    source,
                )
            )
            continue
        # Studio inserts the site attribute as one more shortcode parameter, at
        # the whitespace before the closing ``>}}``.
        offset = len(text[: match.start("space")].encode("utf-8"))
        sites.append(ProjectionSite(kind, (named[kind],), source, offset, accept))
    return sites, diagnostics


def quarto_sites(
    path: PurePosixPath,
    source: bytes,
) -> tuple[tuple[ProjectionSite, ...], tuple[ProjectDiagnostic, ...]]:
    """Return the projection hosts in one document, in source order."""
    text = _decoded(path, source)
    if isinstance(text, ProjectDiagnostic):
        return (), (text,)
    html, html_problems = html_sites(
        path, _masked(text, shortcodes=True).encode("utf-8")
    )
    shortcodes, shortcode_problems = _shortcode_sites(path, text)
    sites = sorted([*html, *shortcodes], key=lambda site: site.offset)
    return tuple(sites), (*html_problems, *shortcode_problems)


def quarto_includes(
    path: PurePosixPath,
    source: bytes,
) -> list[tuple[str, int, int]]:
    """Return the include directives in one UTF-8 document."""
    text = _decoded(path, source)
    return [] if isinstance(text, ProjectDiagnostic) else include_targets(text)
