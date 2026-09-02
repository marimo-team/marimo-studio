"""Discover and instrument literal mounts for the external web fixture."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import PurePosixPath

from marimo_studio.view_providers import (
    MountDeclaration,
    ProjectionKind,
    SourceLocation,
    mount_attribute,
)


@dataclass(frozen=True)
class LiteralMount:
    kind: ProjectionKind
    target: str
    line: int
    column: int
    insertion_offset: int


class _LiteralMountParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.mounts: list[LiteralMount] = []
        self._source = ""
        self._line_offsets = [0]

    def feed(self, data: str) -> None:
        self._source += data
        self._line_offsets = [
            0,
            *(index + 1 for index, char in enumerate(data) if char == "\n"),
        ]
        super().feed(data)

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        self._record(tag, attrs)

    def handle_startendtag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        self._record(tag, attrs)

    def _record(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        declarations: list[tuple[ProjectionKind, str | None]] = []
        if tag == "marimo-cell":
            declarations.append(("cell", attributes.get("name")))
        if tag == "marimo-output":
            declarations.append(("output", attributes.get("value")))
        if "mo-value" in attributes:
            declarations.append(("value", attributes.get("mo-value")))
        if not declarations:
            return
        if len(declarations) != 1:
            raise ValueError("A fixture element must declare one projection")
        kind, target = declarations[0]
        selected = target.strip() if target is not None else ""
        if not selected:
            raise ValueError("A fixture projection requires a literal target")
        line, zero_based_column = self.getpos()
        raw = self.get_starttag_text()
        if raw is None:
            raise ValueError("Could not locate fixture projection start tag")
        before_close = raw[:-1]
        stripped = before_close.rstrip()
        local_offset = (
            len(stripped) - 1 if stripped.endswith("/") else len(before_close)
        )
        character_offset = (
            self._line_offsets[line - 1] + zero_based_column + local_offset
        )
        self.mounts.append(
            LiteralMount(
                kind,
                selected,
                line,
                zero_based_column + 1,
                len(self._source[:character_offset].encode("utf-8")),
            )
        )


def parse_literal_mounts(source: str) -> tuple[LiteralMount, ...]:
    parser = _LiteralMountParser()
    parser.feed(source)
    parser.close()
    return tuple(parser.mounts)


def mount_declarations(
    provider: str,
    path: PurePosixPath,
    mounts: tuple[LiteralMount, ...],
) -> tuple[MountDeclaration, ...]:
    occurrences: dict[tuple[ProjectionKind, str], int] = {}
    result: list[MountDeclaration] = []
    for mount in mounts:
        key = (mount.kind, mount.target)
        occurrence = occurrences.get(key, 0)
        identity = json.dumps(
            [provider, path.as_posix(), mount.kind, mount.target, occurrence],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        result.append(
            MountDeclaration(
                id=f"site-{hashlib.sha256(identity.encode()).hexdigest()}",
                kind=mount.kind,
                source=SourceLocation(path, mount.line, mount.column),
                allowed_targets=(mount.target,),
            )
        )
        occurrences[key] = occurrence + 1
    return tuple(result)


def instrument_literal_mounts(
    source: str,
    mounts: tuple[LiteralMount, ...],
    declarations: tuple[MountDeclaration, ...],
) -> str:
    if len(mounts) != len(declarations):
        raise ValueError("Fixture projection sites changed before build")
    instrumented = source.encode("utf-8")
    for mount, declaration in sorted(
        zip(mounts, declarations, strict=True),
        key=lambda item: item[0].insertion_offset,
        reverse=True,
    ):
        allowed = declaration.allowed_targets
        expected = allowed[0] if allowed is not None and len(allowed) == 1 else None
        if (mount.kind, mount.target) != (declaration.kind, expected):
            raise ValueError("Fixture projection sites changed before build")
        name, value = mount_attribute(declaration.id)
        attribute = f' {name}="{value}"'.encode()
        offset = mount.insertion_offset
        instrumented = instrumented[:offset] + attribute + instrumented[offset:]
    return instrumented.decode("utf-8")
