"""Parse authored view templates and validate projection boundaries."""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

from marimo_studio.errors import TemplateError
from marimo_studio.types import ValueReference
from marimo_studio.values import parse_value_reference

_VOID_ELEMENTS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}


class TemplateParser(HTMLParser):
    """Collect projection hosts and enforce the replaceable shell boundary."""

    def __init__(self) -> None:
        super().__init__()
        self.aliases: list[str] = []
        self.fragment_aliases: list[str] = []
        self.value_references: list[ValueReference] = []
        self.alias_positions: dict[str, tuple[int, int]] = {}
        self.fragment_alias_positions: dict[str, tuple[int, int]] = {}
        self.value_positions: dict[str, tuple[int, int]] = {}
        self.app_shells = 0
        self.heads = 0
        self.bodies = 0
        self.head_closes = 0
        self.body_closes = 0
        self.projection_outside_shell = False
        self.has_reserved_runtime_markup = False
        self._open_tags: list[tuple[str, bool]] = []
        self._shell_depth = 0

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        self._start(tag, attrs, self_closing=tag in _VOID_ELEMENTS)

    def handle_startendtag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        self._start(tag, attrs, self_closing=True)

    def handle_endtag(self, tag: str) -> None:
        if tag == "head":
            self.head_closes += 1
        elif tag == "body":
            self.body_closes += 1
        for index in range(len(self._open_tags) - 1, -1, -1):
            opened_tag, _ = self._open_tags[index]
            if opened_tag != tag:
                continue
            closed = self._open_tags[index:]
            del self._open_tags[index:]
            self._shell_depth -= sum(is_shell for _, is_shell in closed)
            return

    def _start(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
        *,
        self_closing: bool,
    ) -> None:
        attributes = dict(attrs)
        line, column = self.getpos()
        position = (line, column + 1)
        if tag == "head":
            self.heads += 1
        elif tag == "body":
            self.bodies += 1
        if (
            tag == "marimo-filename"
            or attributes.get("id") == "marimo-runtime-root"
            or "data-marimo-studio-runtime" in attributes
            or "data-marimo-studio-dev" in attributes
        ):
            self.has_reserved_runtime_markup = True
        is_shell = attributes.get("id") == "app-shell"
        if is_shell:
            self.app_shells += 1
            self._shell_depth += 1
        if (tag == "marimo-cell" or "mo-value" in attributes) and (
            self._shell_depth == 0
        ):
            self.projection_outside_shell = True
        if tag == "marimo-cell":
            alias = attributes.get("name")
            if alias is None or not alias.strip():
                raise TemplateError(
                    "Every <marimo-cell> requires a non-empty name",
                    line=line,
                    column=column + 1,
                )
            alias = alias.strip()
            self.aliases.append(alias)
            self.alias_positions.setdefault(alias, position)
        fragment_alias = _cell_fragment_alias(attributes.get("hx-get"))
        if fragment_alias is not None:
            self.fragment_aliases.append(fragment_alias)
            self.fragment_alias_positions.setdefault(fragment_alias, position)
        if "mo-value" in attributes:
            source = attributes["mo-value"]
            if source is None:
                raise TemplateError(
                    "Every mo-value attribute requires a reference",
                    line=line,
                    column=column + 1,
                )
            try:
                reference = parse_value_reference(source)
            except ValueError as error:
                raise TemplateError(
                    f"Invalid mo-value reference {source!r} at line {line}: {error}",
                    line=line,
                    column=column + 1,
                ) from error
            self.value_references.append(reference)
            self.value_positions.setdefault(reference.source, position)
        if self_closing:
            if is_shell:
                self._shell_depth -= 1
        else:
            self._open_tags.append((tag, is_shell))


def _cell_fragment_alias(value: str | None) -> str | None:
    if value is None:
        return None
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc:
        return None
    parts = parsed.path.split("/")
    try:
        start = parts.index("_marimo-studio")
    except ValueError:
        return None
    route = parts[start:]
    if (
        len(route) != 5
        or route[1] != "views"
        or route[3] != "cells"
        or not route[2]
        or not route[4]
    ):
        return None
    return route[4]


def validate_template_structure(parser: TemplateParser, source: Path | str) -> None:
    """Validate the document boundary used by checks and runtime injection."""
    if (
        parser.heads != 1
        or parser.head_closes != 1
        or parser.bodies != 1
        or parser.body_closes != 1
    ):
        raise TemplateError(
            f"{source}: expected one <head>, </head>, <body>, and </body>",
            source=source,
        )
    if parser.app_shells != 1:
        raise TemplateError(
            f'{source}: expected one element with id="app-shell"',
            source=source,
        )
