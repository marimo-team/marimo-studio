"""Find the notebook values, outputs, and cells a LaTeX document reads.

``\\marimovalue``, ``\\marimonum``, ``\\marimodate``, ``\\marimotime``, the
``\\IfMarimo`` conditionals, ``\\marimorows``, and ``\\marimoforeach`` read a
value. ``\\marimographics`` places a value as an image in the first format of
``IMAGE_TYPES`` it supports, and ``\\marimocell`` places a named cell's output
when marimo shows it in one of those formats. The scan skips comments,
``\\verb``, and verbatim environments, then reads each command whose braced
argument is literal text. An argument that holds a macro parameter, such as
``#1`` inside a ``\\marimorows`` row, is computed, so Studio never supplies it.
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

# Image formats graphicx places under Tectonic, in order of preference, with
# the file extension each one is read from. PDF keeps a figure's text
# selectable, and PNG and JPEG cover libraries without PDF output.
IMAGE_TYPES = {
    "application/pdf": "pdf",
    "image/png": "png",
    "image/jpeg": "jpg",
}

# Source documents by file suffix, with the editor language Source shows.
LANGUAGES = {
    ".bib": "bibtex",
    ".bst": "plaintext",
    ".cls": "latex",
    ".csv": "plaintext",
    ".json": "json",
    ".md": "markdown",
    ".sty": "latex",
    ".svg": "xml",
    ".tex": "latex",
    ".yaml": "yaml",
    ".yml": "yaml",
}

_COMMANDS = {
    "marimovalue": "value",
    "marimonum": "value",
    "marimodate": "value",
    "marimotime": "value",
    "IfMarimoTF": "value",
    "IfMarimoT": "value",
    "IfMarimoF": "value",
    "marimorows": "value",
    "marimoforeach": "value",
    "marimographics": "output",
    "marimocell": "cell",
}
_COMMAND = re.compile(
    r"\\(?P<name>"
    + "|".join(sorted(_COMMANDS, key=len, reverse=True))
    + r")(?![A-Za-z@])"
)
_VERBATIM = re.compile(
    r"\\begin\s*\{(?P<name>verbatim\*?|Verbatim\*?|BVerbatim|LVerbatim|lstlisting"
    r"|minted|comment)\}"
)
_VERB = re.compile(r"\\(?:verb|lstinline)\*?(?![A-Za-z@])")
# \url prints its argument as written, so a command in it is text. \href reads
# its first argument as written too, but expands commands in it, so % there
# is text and a read there is still a read.
_URL = re.compile(r"\\url(?![A-Za-z@])[ \t]*\{")
_HREF = re.compile(r"\\href(?![A-Za-z@])[ \t]*\{")
# _masked() writes this over a comment, so a selector that a comment splits
# across lines joins up again, as TeX joins it.
_COMMENT = "\0"
_JOINED = re.compile(r"\0+(?:\r?\n[ \t]*)?")


def _verbatim_end(source: str, start: int) -> int:
    """Return the index of the brace that closes a verbatim group at ``start``."""
    depth = 0
    for index in range(start, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return index
    return len(source)


def _blank(characters: list[str], start: int, end: int, fill: str = " ") -> None:
    for index in range(start, end):
        if characters[index] != "\n":
            characters[index] = fill


def _masked(source: str) -> str:
    """Return ``source`` with comments and verbatim text blanked out."""
    characters = list(source)
    index = 0
    while index < len(source):
        character = source[index]
        if character == "\\":
            verbatim = _VERBATIM.match(source, index)
            if verbatim is not None:
                close = source.find(f"\\end{{{verbatim['name']}}}", verbatim.end())
                end = len(source) if close < 0 else close
                _blank(characters, verbatim.end(), end)
                index = end + 1
                continue
            verb = _VERB.match(source, index)
            start = len(source) if verb is None else verb.end()
            # \lstinline takes its options before the delimiter.
            if (
                verb is not None
                and "lstinline" in verb.group()
                and source.startswith("[", start)
            ):
                options = source.find("]", start)
                start = len(source) if options < 0 else options + 1
            if verb is not None and start < len(source):
                delimiter = source[start]
                if delimiter == "{":
                    close = _verbatim_end(source, start)
                else:
                    close = source.find(delimiter, start + 1)
                    line_end = source.find("\n", start)
                    if close < 0 or 0 <= line_end < close:
                        close = start
                _blank(characters, index, close + 1)
                index = close + 1
                continue
            url = _URL.match(source, index)
            if url is not None:
                close = _verbatim_end(source, url.end() - 1)
                _blank(characters, index, close + 1)
                index = close + 1
                continue
            href = _HREF.match(source, index)
            if href is not None:
                index = _verbatim_end(source, href.end() - 1) + 1
                continue
            # A control symbol such as \% or \\ is one token.
            index += 2
        elif character == "%":
            end = source.find("\n", index)
            end = len(source) if end < 0 else end
            _blank(characters, index, end, _COMMENT)
            index = end
        else:
            index += 1
    return "".join(characters)


def _skip_space(source: str, index: int) -> int:
    """Skip the spaces and single line break TeX ignores before an argument."""
    breaks = 0
    while index < len(source) and source[index] in " \t\r\n" + _COMMENT:
        if source[index] == "\n":
            breaks += 1
            if breaks > 1:
                break
        index += 1
    return index


def _group_end(source: str, start: int, opening: str, closing: str) -> int | None:
    """Return the index after the delimiter that closes the group at ``start``."""
    depth = 0
    braces = 0
    index = start
    while index < len(source):
        character = source[index]
        if character == "\\":
            index += 2
            continue
        if opening == "{":
            if character == "{":
                depth += 1
            elif character == "}":
                depth -= 1
                if depth == 0:
                    return index + 1
        elif character == "{":
            braces += 1
        elif character == "}":
            braces -= 1
        elif braces == 0 and character == opening:
            depth += 1
        elif braces == 0 and character == closing:
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    return None


def _argument(source: str, index: int) -> str | None:
    """Return the braced argument after an optional ``[...]`` at ``index``."""
    index = _skip_space(source, index)
    if source.startswith("[", index):
        end = _group_end(source, index, "[", "]")
        if end is None:
            return None
        index = _skip_space(source, end)
    if not source.startswith("{", index):
        return None
    end = _group_end(source, index, "{", "}")
    return None if end is None else source[index + 1 : end - 1]


def latex_reads(path: PurePosixPath, source: str) -> DocumentReads:
    """Return the literal value, output, and cell targets one LaTeX file reads."""
    masked = _masked(source)
    values: list[RenderValue] = []
    outputs: list[RenderOutput] = []
    cells: list[RenderCell] = []
    for match in _COMMAND.finditer(masked):
        argument = _argument(masked, match.end())
        if argument is None or "#" in argument:
            continue
        target = _JOINED.sub("", argument).strip()
        line = source.count("\n", 0, match.start()) + 1
        column = match.start() - (source.rfind("\n", 0, match.start()) + 1) + 1
        location = SourceLocation(path, line, column)
        kind = _COMMANDS[match["name"]]
        if kind == "output":
            outputs.append(RenderOutput(target, location, tuple(IMAGE_TYPES)))
        elif kind == "cell":
            cells.append(RenderCell(target, location, tuple(IMAGE_TYPES)))
        else:
            values.append(RenderValue(target, location))
    return DocumentReads(tuple(values), tuple(outputs), tuple(cells))
