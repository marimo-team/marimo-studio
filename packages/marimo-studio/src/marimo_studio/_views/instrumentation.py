"""Add Studio site attributes to a build snapshot and account for them after.

Providers report where each projection host starts. Studio inserts the runtime
site attribute into its private snapshot copy before ``build()``, maps build
diagnostics back to authored columns, and checks that the built files still
carry every site.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath

from marimo_studio._artifacts.limits import ARTIFACT_OUTPUT_BUDGET
from marimo_studio._filesystem.budgets import BUILD_INPUT_BUDGET
from marimo_studio._filesystem.files import FileTree
from marimo_studio._views.records import DiagnosticsError
from marimo_studio.view_providers._artifact_sites import (
    SITE_ATTRIBUTE,
    ArtifactSite,
    artifact_sites,
)
from marimo_studio.view_providers._records import (
    ProjectDiagnostic,
    ProjectionSite,
    SourceLocation,
)

_SITE_ID = re.compile(rb"site-[0-9a-f]{64}")
_TAG_CONTINUATIONS = frozenset((b" ", b"\t", b"\n", b"\r", b"\f", b"/", b">"))


@dataclass(frozen=True)
class SiteInsertion:
    """One inserted attribute at an authored line and character column."""

    path: PurePosixPath
    line: int
    column: int
    length: int


def _position(text: bytes, offset: int) -> tuple[int, int]:
    line_start = text.rfind(b"\n", 0, offset) + 1
    line = text.count(b"\n", 0, offset) + 1
    return line, len(text[line_start:offset].decode("utf-8")) + 1


def _site_error(site: ProjectionSite, message: str, hint: str) -> DiagnosticsError:
    return DiagnosticsError(
        (
            ProjectDiagnostic(
                "projection-site-invalid",
                "error",
                message,
                hint,
                site.source,
            ),
        )
    )


def instrument_sites(
    root: Path,
    sites: tuple[ProjectionSite, ...],
) -> tuple[tuple[ArtifactSite, ...], tuple[SiteInsertion, ...]]:
    """Insert each site's attribute at its provider-reported offset.

    Returns the artifact sites in site order and the insertions made. Raises
    ``DiagnosticsError`` located at the first host whose offset is invalid.
    """
    identified = artifact_sites(sites)
    grouped: dict[PurePosixPath, list[tuple[ProjectionSite, ArtifactSite]]] = {}
    for site, identity in zip(sites, identified, strict=True):
        grouped.setdefault(site.source.path, []).append((site, identity))
    insertions: list[SiteInsertion] = []
    tree = FileTree(root)
    for relative, file_sites in grouped.items():
        path = root.joinpath(*relative.parts)
        source = tree.read(path, max_bytes=BUILD_INPUT_BUDGET.max_file_bytes)
        content = source.content
        parts: list[bytes] = []
        cursor = 0
        for site, identity in sorted(file_sites, key=lambda item: item[0].offset):
            offset = site.offset
            if content[offset : offset + 1] not in _TAG_CONTINUATIONS:
                raise _site_error(
                    site,
                    f"Projection site offset {offset} in {relative} is outside "
                    "its host start tag.",
                    "Report the UTF-8 byte offset before the start tag's closing "
                    "> or /> in the file as stored, without newline translation.",
                )
            line, column = _position(content, offset)
            # Providers count columns in their own units, such as UTF-16, so
            # only the line is comparable. The byte check above keeps the
            # offset inside a start tag.
            if line < site.source.line:
                raise _site_error(
                    site,
                    f"Projection site offset {offset} precedes its host at "
                    f"{relative}:{site.source.line}:{site.source.column}.",
                    "Report a UTF-8 byte offset inside the host start tag.",
                )
            text = f' {SITE_ATTRIBUTE}="{identity.id}"'.encode()
            parts.extend((content[cursor:offset], text))
            cursor = offset
            insertions.append(SiteInsertion(relative, line, column, len(text)))
        parts.append(content[cursor:])
        tree.write(path, b"".join(parts), expect=source.version)
    return identified, tuple(insertions)


def _authored_column(
    column: int,
    insertions: Iterable[SiteInsertion],
) -> int:
    shift = 0
    for insertion in sorted(insertions, key=lambda item: item.column):
        start = insertion.column + shift
        if column < start:
            break
        if column < start + insertion.length:
            return insertion.column
        shift += insertion.length
    return column - shift


def authored_diagnostics(
    diagnostics: tuple[ProjectDiagnostic, ...],
    insertions: tuple[SiteInsertion, ...],
) -> tuple[ProjectDiagnostic, ...]:
    """Map build diagnostic columns from the instrumented snapshot to source."""
    by_line: dict[tuple[PurePosixPath, int], list[SiteInsertion]] = {}
    for insertion in insertions:
        by_line.setdefault((insertion.path, insertion.line), []).append(insertion)
    mapped: list[ProjectDiagnostic] = []
    for diagnostic in diagnostics:
        source = diagnostic.source
        line_insertions = (
            by_line.get((source.path, source.line)) if source is not None else None
        )
        if source is None or line_insertions is None:
            mapped.append(diagnostic)
            continue
        column = _authored_column(source.column, line_insertions)
        mapped.append(
            replace(
                diagnostic,
                source=SourceLocation(source.path, source.line, column),
            )
        )
    return tuple(mapped)


def missing_site_diagnostics(
    files_root: Path,
    sites: tuple[ArtifactSite, ...],
) -> tuple[ProjectDiagnostic, ...]:
    """Warn about sites whose site ID appears in none of the published files."""
    expected = {site.id.encode() for site in sites}
    found: set[bytes] = set()
    tree = FileTree(files_root)
    for path, _size in tree.regular_files(
        files_root,
        max_entries=ARTIFACT_OUTPUT_BUDGET.max_files,
    ):
        if found == expected:
            break
        content = tree.read(path, max_bytes=ARTIFACT_OUTPUT_BUDGET.max_file_bytes)
        found.update(expected.intersection(_SITE_ID.findall(content.content)))
    return tuple(
        ProjectDiagnostic(
            "projection-site-missing",
            "warning",
            f"The built view has no host for the {site.kind} site at "
            f"{site.source.path}:{site.source.line}:{site.source.column}.",
            f"Keep the host and the {SITE_ATTRIBUTE} attribute Studio adds to it "
            "in the built output.",
            site.source,
        )
        for site in sites
        if site.id.encode() not in found
    )
