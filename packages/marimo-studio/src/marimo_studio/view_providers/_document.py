"""Parse provider HTML documents and validate their projection boundary."""

from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from marimo_studio.errors import ViewProjectError
from marimo_studio.view_providers._css_resources import css_resource_urls
from marimo_studio.view_providers._mounts import MOUNT_ATTRIBUTE
from marimo_studio.view_providers._targets import parse_value_target

_PROJECTION_USAGE_HINT = (
    'Use <marimo-cell name="..."> for a complete cell display, '
    '<marimo-output value="..."> for one Python object, or mo-value="..." '
    "when browser code needs JSON-compatible data."
)

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


@dataclass(frozen=True)
class HTMLMountDeclaration:
    """One normalized projection declaration and its UTF-8 insertion offset."""

    kind: Literal["cell", "output", "value"]
    target: str
    position: tuple[int, int]
    insertion_offset: int


@dataclass(frozen=True)
class HTMLResource:
    """One fetched URL declared by an HTML document."""

    tag: str
    attribute: str
    value: str
    position: tuple[int, int]
    relations: tuple[str, ...] = ()
    insertion_offset: int | None = None


class HTMLLocalResourceError(ViewProjectError):
    """A document declares a project-local resource outside its contract."""


@dataclass(frozen=True)
class HTMLInlineScript:
    """One executable inline script and its first source character."""

    content: str
    position: tuple[int, int]


_FETCHED_ATTRIBUTES = {
    "audio": ("src",),
    "embed": ("src",),
    "iframe": ("src",),
    "img": ("src",),
    "input": ("src",),
    "object": ("data",),
    "script": ("src", "href", "xlink:href"),
    "source": ("src",),
    "track": ("src",),
    "video": ("src", "poster"),
}
_FETCHED_SVG_HREF_TAGS = frozenset(
    {
        "animate",
        "animatemotion",
        "animatetransform",
        "cursor",
        "feimage",
        "image",
        "lineargradient",
        "mpath",
        "pattern",
        "radialgradient",
        "set",
        "textpath",
        "use",
    }
)
_FETCHED_LINK_RELATIONS = frozenset(
    {
        "apple-touch-icon",
        "icon",
        "manifest",
        "mask-icon",
        "modulepreload",
        "prefetch",
        "preload",
        "stylesheet",
    }
)
_EXECUTABLE_SCRIPT_TYPES = frozenset(
    {
        "",
        "application/ecmascript",
        "application/javascript",
        "application/x-ecmascript",
        "application/x-javascript",
        "module",
        "text/ecmascript",
        "text/javascript",
        "text/javascript1.0",
        "text/javascript1.1",
        "text/javascript1.2",
        "text/javascript1.3",
        "text/javascript1.4",
        "text/javascript1.5",
        "text/jscript",
        "text/livescript",
        "text/x-ecmascript",
        "text/x-javascript",
    }
)


def _advance_source_position(
    source: str,
    start: int,
    end: int,
    line: int,
    column: int,
) -> tuple[int, int]:
    segment = source[start:end]
    added_lines = segment.count("\n")
    if added_lines:
        return line + added_lines, len(segment.rsplit("\n", maxsplit=1)[-1]) + 1
    return line, column + len(segment)


def is_local_resource_url(value: str) -> bool:
    """Return whether a fetched URL resolves through the document base."""
    selected = value.strip()
    if not selected or selected.startswith("#"):
        return False
    parsed = urlsplit(selected)
    if parsed.scheme.casefold() in {"http", "https"} and not parsed.hostname:
        raise ValueError("HTTP and HTTPS resource URLs must include // and a host")
    return not parsed.scheme and not parsed.netloc


def _resource_is_local(value: str, position: tuple[int, int]) -> bool:
    try:
        return is_local_resource_url(value)
    except ValueError as error:
        line, column = position
        raise ViewProjectError(
            f"Invalid resource URL {value!r}: {error}",
            line=line,
            column=column,
        ) from error


def _srcset_urls(source: str) -> tuple[str, ...]:
    """Collect responsive image candidates using HTML token boundaries."""
    urls: list[str] = []
    index = 0
    while index < len(source):
        while index < len(source) and (source[index].isspace() or source[index] == ","):
            index += 1
        start = index
        while index < len(source) and not source[index].isspace():
            index += 1
        candidate = source[start:index]
        if not candidate:
            break
        trailing_commas = len(candidate) - len(candidate.rstrip(","))
        if trailing_commas:
            candidate = candidate[:-trailing_commas]
            if candidate:
                urls.append(candidate)
            continue
        urls.append(candidate)
        parentheses = 0
        while index < len(source):
            character = source[index]
            if character == "(":
                parentheses += 1
            elif character == ")" and parentheses:
                parentheses -= 1
            elif character == "," and not parentheses:
                index += 1
                break
            index += 1
    return tuple(urls)


class HTMLDocumentParser(HTMLParser):
    """Collect projection hosts and enforce the replaceable shell boundary."""

    def __init__(self) -> None:
        super().__init__()
        self.mounts: list[HTMLMountDeclaration] = []
        self.resources: list[HTMLResource] = []
        self.local_resources: list[HTMLResource] = []
        self.inline_scripts: list[HTMLInlineScript] = []
        self.app_shells = 0
        self.heads = 0
        self.bodies = 0
        self.head_closes = 0
        self.body_closes = 0
        self.projection_outside_shell = False
        self.has_reserved_runtime_markup = False
        self.canonical_head_order = True
        self._document_phase = "before-html"
        self.authored_mount_declaration_position: tuple[int, int] | None = None
        self.authored_source_revision_position: tuple[int, int] | None = None
        self.import_map_position: tuple[int, int] | None = None
        self.base_href_position: tuple[int, int] | None = None
        self._open_tags: list[tuple[str, bool, bool]] = []
        self._shell_depth = 0
        self._source = ""
        self._line_offsets = [0]
        self._insertion_character_offset = 0
        self._insertion_byte_offset = 0
        self._inline_script = False

    def feed(self, data: str) -> None:
        self._source += data
        self._line_offsets = [0]
        self._line_offsets.extend(
            index + 1
            for index, character in enumerate(self._source)
            if character == "\n"
        )
        super().feed(data)

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
        foreign_content = tag in {"svg", "math"} or any(
            opened in {"svg", "math"} for opened, _, _ in self._open_tags
        )
        if tag not in _VOID_ELEMENTS and not foreign_content:
            line, column = self.getpos()
            raise ViewProjectError(
                f"<{tag}> cannot use self-closing syntax in HTML. Use </{tag}>.",
                line=line,
                column=column + 1,
            )
        self._start(tag, attrs, self_closing=True)

    def handle_endtag(self, tag: str) -> None:
        if tag == "head":
            self.head_closes += 1
        elif tag == "body":
            self.body_closes += 1
        elif tag == "script":
            self._inline_script = False
        for index in range(len(self._open_tags) - 1, -1, -1):
            opened_tag, _, _ = self._open_tags[index]
            if opened_tag != tag:
                continue
            closed = self._open_tags[index:]
            del self._open_tags[index:]
            self._shell_depth -= sum(is_shell for _, is_shell, _ in closed)
            return

    def handle_data(self, data: str) -> None:
        if self._document_phase in {"before-html", "before-head"} and data.strip():
            self.canonical_head_order = False
        if self._open_tags and self._open_tags[-1][0] == "script":
            if self._inline_script:
                line, column = self.getpos()
                self.inline_scripts.append(HTMLInlineScript(data, (line, column + 1)))
            return
        if not self._open_tags or self._open_tags[-1][0] != "style":
            return
        line, column = self.getpos()
        resource_line = line
        resource_column = column + 1
        previous_offset = 0
        for value, offset in css_resource_urls(data):
            if offset < previous_offset:
                raise ViewProjectError("CSS resources are out of source order")
            resource_line, resource_column = _advance_source_position(
                data,
                previous_offset,
                offset,
                resource_line,
                resource_column,
            )
            previous_offset = offset
            position = (resource_line, resource_column)
            resource = HTMLResource("style", "url", value, position)
            self.resources.append(resource)
            if not _resource_is_local(value, position):
                continue
            self.local_resources.append(resource)

    def _start(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
        *,
        self_closing: bool,
    ) -> None:
        line, column = self.getpos()
        position = (line, column + 1)
        if self._document_phase == "before-html":
            if tag == "html":
                self._document_phase = "before-head"
            else:
                self.canonical_head_order = False
        elif self._document_phase == "before-head":
            if tag == "head":
                self._document_phase = "in-head"
            else:
                self.canonical_head_order = False
        attribute_names: set[str] = set()
        for name, _ in attrs:
            normalized_name = name.casefold()
            if normalized_name in attribute_names:
                raise ViewProjectError(
                    f"Duplicate HTML attribute {name!r}",
                    line=line,
                    column=column + 1,
                )
            attribute_names.add(normalized_name)
        attributes = dict(attrs)
        if tag == "base" and "href" in attributes and self.base_href_position is None:
            self.base_href_position = position
        if tag == "script":
            script_type = (attributes.get("type") or "").strip().casefold()
            if script_type == "importmap" and self.import_map_position is None:
                self.import_map_position = position
            self._inline_script = (
                "src" not in attributes and script_type in _EXECUTABLE_SCRIPT_TYPES
            )
        inline_style = attributes.get("style")
        if inline_style is not None:
            for value, _ in css_resource_urls(inline_style):
                resource = HTMLResource(tag, "style", value, position)
                self.resources.append(resource)
                if _resource_is_local(value, position):
                    self.local_resources.append(resource)
        responsive_attribute = "imagesrcset" if tag == "link" else "srcset"
        responsive = attributes.get(responsive_attribute)
        if responsive is not None:
            for value in _srcset_urls(responsive):
                resource = HTMLResource(
                    tag,
                    responsive_attribute,
                    value,
                    position,
                )
                self.resources.append(resource)
                if _resource_is_local(value, position):
                    self.local_resources.append(resource)
        fetched = _FETCHED_ATTRIBUTES.get(tag, ())
        if tag in _FETCHED_SVG_HREF_TAGS:
            fetched = (*fetched, "href", "xlink:href")
        relations: set[str] = set()
        if tag == "link":
            relations = {
                item.casefold() for item in (attributes.get("rel") or "").split()
            }
            if relations & _FETCHED_LINK_RELATIONS:
                fetched = ("href",)
        for attribute in fetched:
            value = attributes.get(attribute)
            if value is None:
                continue
            resource = HTMLResource(
                tag,
                attribute,
                value.strip(),
                position,
                tuple(sorted(relations)),
                insertion_offset=(
                    self._start_tag_insertion_offset(line, column)
                    if tag == "script" and attribute == "src"
                    else None
                ),
            )
            self.resources.append(resource)
            if _resource_is_local(value, position):
                self.local_resources.append(resource)
        if (
            MOUNT_ATTRIBUTE in attributes
            and self.authored_mount_declaration_position is None
        ):
            self.authored_mount_declaration_position = position
        if (
            "data-marimo-studio-source-revision" in attributes
            and self.authored_source_revision_position is None
        ):
            self.authored_source_revision_position = position
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
        if (tag in ("marimo-cell", "marimo-output") or "mo-value" in attributes) and (
            self._shell_depth == 0
        ):
            self.projection_outside_shell = True
        declarations: list[tuple[Literal["cell", "output", "value"], str]] = []
        if tag == "marimo-cell":
            alias = attributes.get("name")
            if alias is None or not alias.strip():
                raise ViewProjectError(
                    "<marimo-cell> requires a non-empty name.",
                    line=line,
                    column=column + 1,
                    hint=_PROJECTION_USAGE_HINT,
                )
            declarations.append(("cell", alias.strip()))
        if "mo-value" in attributes:
            source = attributes["mo-value"]
            if source is None:
                raise ViewProjectError(
                    "mo-value requires a non-empty selector.",
                    line=line,
                    column=column + 1,
                    hint=_PROJECTION_USAGE_HINT,
                )
            try:
                reference = parse_value_target(source)
            except ValueError as error:
                raise ViewProjectError(
                    f"Invalid mo-value reference {source!r} at line {line}: {error}",
                    line=line,
                    column=column + 1,
                ) from error
            declarations.append(("value", reference.source))
        if tag == "marimo-output":
            source = attributes.get("value")
            if source is None:
                raise ViewProjectError(
                    "<marimo-output> requires a non-empty value.",
                    line=line,
                    column=column + 1,
                    hint=_PROJECTION_USAGE_HINT,
                )
            try:
                reference = parse_value_target(source)
            except ValueError as error:
                raise ViewProjectError(
                    f"Invalid marimo-output value {source!r} at line {line}: {error}",
                    line=line,
                    column=column + 1,
                ) from error
            declarations.append(("output", reference.source))
        if len(declarations) > 1:
            raise ViewProjectError(
                "One element cannot declare more than one projection kind.",
                line=line,
                column=column + 1,
                hint=_PROJECTION_USAGE_HINT,
            )
        if declarations:
            if any(is_projection for _, _, is_projection in self._open_tags):
                raise ViewProjectError(
                    "Projection hosts cannot contain other projection hosts. "
                    "Place them beside each other.",
                    line=line,
                    column=column + 1,
                )
            kind, target = declarations[0]
            self.mounts.append(
                HTMLMountDeclaration(
                    kind,
                    target,
                    position,
                    self._start_tag_insertion_offset(line, column),
                )
            )
        if self_closing:
            if tag == "script":
                self._inline_script = False
            if is_shell:
                self._shell_depth -= 1
        else:
            self._open_tags.append((tag, is_shell, bool(declarations)))

    def _start_tag_insertion_offset(self, line: int, column: int) -> int:
        raw = self.get_starttag_text()
        if raw is None or not raw.endswith(">"):
            raise ViewProjectError(
                "HTML parser could not locate a projection start tag",
                line=line,
                column=column + 1,
            )
        before_close = raw[:-1]
        stripped = before_close.rstrip()
        local_offset = (
            len(stripped) - 1 if stripped.endswith("/") else len(before_close)
        )
        try:
            character_offset = self._line_offsets[line - 1] + column + local_offset
        except IndexError as error:
            raise ViewProjectError(
                "HTML parser returned an invalid source position",
                line=line,
                column=column + 1,
            ) from error
        if character_offset < self._insertion_character_offset:
            raise ViewProjectError(
                "HTML parser returned projection tags out of source order",
                line=line,
                column=column + 1,
            )
        self._insertion_byte_offset += len(
            self._source[self._insertion_character_offset : character_offset].encode(
                "utf-8"
            )
        )
        self._insertion_character_offset = character_offset
        return self._insertion_byte_offset


def validate_html_document(
    parser: HTMLDocumentParser,
    source: Path | str,
) -> None:
    """Validate the document boundary used by checks and runtime injection."""
    if not parser.canonical_head_order:
        raise ViewProjectError(
            f"{source}: expected <html> followed by <head> before authored content",
            source=source,
        )
    if (
        parser.heads != 1
        or parser.head_closes != 1
        or parser.bodies != 1
        or parser.body_closes != 1
    ):
        raise ViewProjectError(
            f"{source}: expected one <head>, </head>, <body>, and </body>",
            source=source,
        )
    if parser.app_shells != 1:
        raise ViewProjectError(
            f'{source}: expected one element with id="app-shell"',
            source=source,
        )
