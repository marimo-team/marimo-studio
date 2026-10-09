"""Find the notebook values, outputs, and cells a Typst document reads.

``marimo_value("...")`` reads a JSON value. ``marimo_output("...")`` places a
value as an image in the first format of ``IMAGE_TYPES`` it supports, and
``marimo_cell("...")`` places a named cell's output when marimo shows it in one
of those formats. The scan skips comments and raw text, then reads each call
whose first argument is a string literal. Calls with computed targets are not
listed, so Studio never supplies them and the template's default applies.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from marimo_studio.view_providers import (
    RenderCell,
    RenderOutput,
    RenderValue,
    SourceLocation,
)
from marimo_studio.view_providers._builtin._typeset import DocumentReads

# Image formats Typst places with image(), in order of preference, with the
# file extension Typst reads each one from. PDF keeps a figure's text
# selectable, and SVG and PNG cover libraries without PDF output.
IMAGE_TYPES = {
    "application/pdf": "pdf",
    "image/svg+xml": "svg",
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
}

_CALL = re.compile(r'(?<![\w-])marimo_(?P<kind>value|output|cell)\s*\(\s*"')


def _blank(characters: list[str], start: int, end: int) -> None:
    for index in range(start, end):
        if characters[index] != "\n":
            characters[index] = " "


def _masked(source: str) -> str:
    characters = list(source)
    index = 0
    while index < len(source):
        if source.startswith("//", index):
            if index > 0 and source[index - 1] == ":":
                index += 2
                continue
            end = source.find("\n", index)
            end = len(source) if end < 0 else end
            _blank(characters, index, end)
            index = end
        elif source.startswith("/*", index):
            depth, end = 1, index + 2
            while end < len(source) and depth:
                if source.startswith("/*", end):
                    depth, end = depth + 1, end + 2
                elif source.startswith("*/", end):
                    depth, end = depth - 1, end + 2
                else:
                    end += 1
            _blank(characters, index, end)
            index = end
        elif source[index] == "`":
            end = index
            while end < len(source) and source[end] == "`":
                end += 1
            ticks = end - index
            if ticks == 2:
                index = end
                continue
            closing = source.find("`" * ticks, end)
            closing = len(source) if closing < 0 else closing + ticks
            _blank(characters, index, closing)
            index = closing
        elif source[index] == '"':
            # A string literal can hold comment markers, such as "/*", so skip
            # a string that closes on its line.
            index = _string_end(source, index + 1) or index + 1
        elif source[index] == "\\":
            index += 2
        else:
            index += 1
    return "".join(characters)


def _string_end(source: str, start: int) -> int | None:
    """Return the index after the quote that closes a string, if on its line."""
    index = start
    while index < len(source):
        character = source[index]
        if character == '"':
            return index + 1
        if character == "\n":
            return None
        index += 2 if character == "\\" else 1
    return None


def _string(source: str, start: int) -> str | None:
    characters: list[str] = []
    index = start
    while index < len(source):
        character = source[index]
        if character == '"':
            return "".join(characters)
        if character == "\n":
            return None
        if character == "\\" and index + 1 < len(source):
            escaped = source[index + 1]
            if escaped == "u" and source.startswith("{", index + 2):
                closing = source.find("}", index + 3)
                if closing < 0:
                    return None
                try:
                    characters.append(chr(int(source[index + 3 : closing], 16)))
                except ValueError:
                    return None
                index = closing + 1
                continue
            characters.append({"n": "\n", "t": "\t", "r": "\r"}.get(escaped, escaped))
            index += 2
            continue
        characters.append(character)
        index += 1
    return None


def typst_reads(path: PurePosixPath, source: str) -> DocumentReads:
    """Return the literal value, output, and cell targets one Typst file reads."""
    values: list[RenderValue] = []
    outputs: list[RenderOutput] = []
    cells: list[RenderCell] = []
    for match in _CALL.finditer(_masked(source)):
        target = _string(source, match.end())
        if target is None:
            continue
        line = source.count("\n", 0, match.start()) + 1
        column = match.start() - (source.rfind("\n", 0, match.start()) + 1) + 1
        location = SourceLocation(path, line, column)
        if match["kind"] == "output":
            outputs.append(RenderOutput(target, location, tuple(IMAGE_TYPES)))
        elif match["kind"] == "cell":
            cells.append(RenderCell(target, location, tuple(IMAGE_TYPES)))
        else:
            values.append(RenderValue(target, location))
    return DocumentReads(tuple(values), tuple(outputs), tuple(cells))
