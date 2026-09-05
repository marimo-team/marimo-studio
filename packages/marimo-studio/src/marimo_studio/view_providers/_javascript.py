"""Read browser JavaScript module dependencies from a bounded syntax tree."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Literal

import tree_sitter_javascript
from tree_sitter import Language, Node, Parser

MAX_SPECIFIER_CHARACTERS = 4_096
TRUNCATED_SPECIFIER = "\0marimo-studio:truncated-module-specifier"
_LANGUAGE = Language(tree_sitter_javascript.language())
_SIMPLE_ESCAPES = {
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "v": "\v",
}
_DEBUGGER_STATEMENT_PARENTS = frozenset(
    {
        "do_statement",
        "else_clause",
        "for_in_statement",
        "for_statement",
        "if_statement",
        "labeled_statement",
        "program",
        "statement_block",
        "switch_case",
        "switch_default",
        "while_statement",
        "with_statement",
    }
)
_ECMASCRIPT_SPACES = tuple(
    item.encode("utf-8")
    for item in (
        "\t",
        "\v",
        "\f",
        " ",
        "\u00a0",
        "\u1680",
        "\u2000",
        "\u2001",
        "\u2002",
        "\u2003",
        "\u2004",
        "\u2005",
        "\u2006",
        "\u2007",
        "\u2008",
        "\u2009",
        "\u200a",
        "\u202f",
        "\u205f",
        "\u3000",
        "\ufeff",
    )
)
DependencyKind = Literal[
    "dynamic import",
    "import",
    "import meta URL",
    "parse error",
    "re-export",
    "source import",
]


@dataclass(frozen=True)
class JavaScriptDependency:
    """One module dependency or unsupported dependency expression."""

    kind: DependencyKind
    specifier: str | None
    offset: int


@dataclass(frozen=True)
class _ByteDependency:
    kind: DependencyKind
    specifier: str | None
    offset: int


def _character_offsets(source: bytes, offsets: set[int]) -> dict[int, int]:
    result: dict[int, int] = {}
    byte_cursor = 0
    character_cursor = 0
    for offset in sorted(offsets):
        character_cursor += len(source[byte_cursor:offset].decode("utf-8"))
        result[offset] = character_cursor
        byte_cursor = offset
    return result


def _decode_escape(source: str) -> str | None:
    if len(source) < 2 or source[0] != "\\":
        return None
    value = source[1:]
    if value in _SIMPLE_ESCAPES:
        return _SIMPLE_ESCAPES[value]
    if value in {"\n", "\r", "\r\n", "\u2028", "\u2029"}:
        return ""
    if value and value[0] in "01234567":
        maximum = 3 if value[0] in "0123" else 2
        digits = value[:maximum]
        if all(item in "01234567" for item in digits):
            return chr(int(digits, 8)) + value[len(digits) :]
    if value.startswith("x") and len(value) == 3:
        digits = value[1:]
    elif value.startswith("u{") and value.endswith("}"):
        digits = value[2:-1]
    elif value.startswith("u") and len(value) == 5:
        digits = value[1:]
    else:
        return value
    try:
        codepoint = int(digits, 16)
        return chr(codepoint) if codepoint <= 0x10FFFF else None
    except (ValueError, OverflowError):
        return None


def _literal(node: Node, source: bytes) -> str | None:
    if node.type not in {"string", "template_string"}:
        return None
    value: list[str] = []
    characters = 0
    for child in node.named_children:
        if child.type == "template_substitution":
            return None
        text = source[child.start_byte : child.end_byte].decode("utf-8")
        segment = _decode_escape(text) if child.type == "escape_sequence" else text
        if segment is None:
            return None
        characters += len(segment)
        if characters > MAX_SPECIFIER_CHARACTERS:
            return TRUNCATED_SPECIFIER
        value.append(segment)
    return "".join(value)


def _dynamic_dependency(node: Node, source: bytes) -> _ByteDependency | None:
    function = node.child_by_field_name("function")
    if function is None or function.type != "import":
        return None
    errors = [child for child in node.named_children if child.type == "ERROR"]
    kind: Literal["dynamic import", "source import"] = (
        "source import" if errors else "dynamic import"
    )
    arguments = node.child_by_field_name("arguments")
    argument = (
        arguments.named_children[0] if arguments and arguments.named_children else None
    )
    return _ByteDependency(
        kind,
        None
        if kind == "source import" or argument is None
        else _literal(argument, source),
        argument.start_byte if argument else function.start_byte,
    )


def _import_meta_url_dependency(
    node: Node,
    source: bytes,
) -> _ByteDependency | None:
    constructor = node.child_by_field_name("constructor")
    arguments = node.child_by_field_name("arguments")
    if (
        node.type != "new_expression"
        or constructor is None
        or source[constructor.start_byte : constructor.end_byte] != b"URL"
        or arguments is None
        or len(arguments.named_children) != 2
    ):
        return None
    specifier, base = arguments.named_children
    if source[base.start_byte : base.end_byte] != b"import.meta.url":
        return None
    return _ByteDependency(
        "import meta URL",
        _literal(specifier, source),
        specifier.start_byte,
    )


def _has_asi_boundary(source: bytes, index: int) -> bool:
    while index < len(source):
        space = next(
            (item for item in _ECMASCRIPT_SPACES if source.startswith(item, index)),
            None,
        )
        if space is not None:
            index += len(space)
            continue
        if source.startswith((b"//", b"<!--"), index):
            return True
        if source.startswith(b"/*", index):
            close = source.find(b"*/", index + 2)
            if close < 0:
                return False
            comment = source[index : close + 2]
            if any(
                marker in comment
                for marker in (b"\n", b"\r", b"\xe2\x80\xa8", b"\xe2\x80\xa9")
            ):
                return True
            index = close + 2
            continue
        return source[index : index + 1] in {b"\n", b"\r", b"}"} or source.startswith(
            (b"\xe2\x80\xa8", b"\xe2\x80\xa9"), index
        )
    return True


def _allows_automatic_semicolon(node: Node, source: bytes) -> bool:
    return (
        node.is_missing
        and node.type == ";"
        and _has_asi_boundary(source, node.start_byte)
    )


def _known_parser_gap(node: Node, source: bytes) -> bool:
    if node.type != "ERROR" or source[node.start_byte : node.end_byte] != b"debugger":
        return False
    if node.parent is None or node.parent.type not in _DEBUGGER_STATEMENT_PARENTS:
        return False
    return _has_asi_boundary(source, node.end_byte)


def javascript_dependencies(source: str) -> Iterator[JavaScriptDependency]:
    """Yield module dependencies and fail-closed parse diagnostics."""
    payload = source.encode("utf-8")
    root = Parser(_LANGUAGE).parse(payload).root_node
    dependencies: list[_ByteDependency] = []
    handled_errors: set[tuple[int, int]] = set()
    parse_errors: list[Node] = []
    saw_tree_error = False
    stack = [root]
    while stack:
        node = stack.pop()
        if node.type == "import_statement":
            specifier = node.child_by_field_name("source")
            if specifier is not None:
                dependencies.append(
                    _ByteDependency(
                        "import",
                        _literal(specifier, payload),
                        specifier.start_byte,
                    )
                )
        elif node.type == "export_statement":
            specifier = node.child_by_field_name("source")
            if specifier is not None:
                dependencies.append(
                    _ByteDependency(
                        "re-export",
                        _literal(specifier, payload),
                        specifier.start_byte,
                    )
                )
        elif node.type == "call_expression":
            dependency = _dynamic_dependency(node, payload)
            if dependency is not None:
                dependencies.append(dependency)
                if dependency.kind == "source import":
                    handled_errors.update(
                        (child.start_byte, child.end_byte)
                        for child in node.named_children
                        if child.type == "ERROR"
                    )
        elif node.type == "new_expression":
            dependency = _import_meta_url_dependency(node, payload)
            if dependency is not None:
                dependencies.append(dependency)
        if node.type == "ERROR":
            saw_tree_error = True
            if _known_parser_gap(node, payload):
                handled_errors.add((node.start_byte, node.end_byte))
            else:
                parse_errors.append(node)
        elif node.is_missing:
            saw_tree_error = True
            if not _allows_automatic_semicolon(node, payload):
                parse_errors.append(node)
        stack.extend(reversed(node.children))

    for error in parse_errors:
        if (error.start_byte, error.end_byte) in handled_errors:
            continue
        dependencies.append(
            _ByteDependency(
                "parse error",
                None,
                error.start_byte,
            )
        )
    if root.has_error and not saw_tree_error:
        dependencies.append(_ByteDependency("parse error", None, 0))
    offsets = _character_offsets(payload, {item.offset for item in dependencies})
    for dependency in sorted(dependencies, key=lambda item: item.offset):
        yield JavaScriptDependency(
            dependency.kind,
            dependency.specifier,
            offsets[dependency.offset],
        )
