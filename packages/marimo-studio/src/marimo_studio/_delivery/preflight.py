"""Inspect a staged static bundle before it can replace its destination."""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import Literal
from urllib.parse import unquote, urlsplit

from marimo_studio._artifacts.limits import ARTIFACT_OUTPUT_BUDGET
from marimo_studio._delivery.portability import ProjectionPortability, StaticRuntime
from marimo_studio._filesystem.secure import SecureDirectory, SecureFileError
from marimo_studio.view_providers import SourceLocation
from marimo_studio.view_providers._css_resources import css_resource_urls
from marimo_studio.view_providers._document import HTMLDocumentParser
from marimo_studio.view_providers._javascript import (
    TRUNCATED_SPECIFIER,
    javascript_dependencies,
)

_TEXT_SUFFIXES = frozenset({".css", ".cjs", ".htm", ".html", ".js", ".mjs"})
_MAX_TEXT_FILE_BYTES = 64 * 1024 * 1024
_MAX_TEXT_TOTAL_BYTES = 256 * 1024 * 1024
_REMOTE_SCHEMES = frozenset({"blob", "data", "http", "https"})


@dataclass(frozen=True, slots=True)
class StaticPreflightIssue:
    """One actionable problem found in a staged browser artifact."""

    code: str
    severity: Literal["warning", "error"]
    message: str
    source: SourceLocation
    reference: str | None = None
    hint: str = ""

    def to_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "source": self.source.to_dict(),
            "hint": self.hint,
        }
        if self.reference is not None:
            value["reference"] = self.reference
        return value


@dataclass(frozen=True, slots=True)
class StaticPreflightReport:
    """Machine-readable evidence from one staged static delivery check."""

    view: str
    runtime: StaticRuntime
    document: PurePosixPath
    files: int
    browser_files: int
    inspected_files: int
    references: int
    projections: tuple[ProjectionPortability, ...]
    issues: tuple[StaticPreflightIssue, ...]

    @property
    def ok(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": 1,
            "ok": self.ok,
            "view": self.view,
            "runtime": self.runtime,
            "document": self.document.as_posix(),
            "files": self.files,
            "browser_files": self.browser_files,
            "inspected_files": self.inspected_files,
            "references": self.references,
            "projections": [item.to_dict() for item in self.projections],
            "issues": [item.to_dict() for item in self.issues],
        }


def _position(source: str, offset: int) -> tuple[int, int]:
    line = source.count("\n", 0, offset) + 1
    previous = source.rfind("\n", 0, offset)
    return line, offset - previous


def _read_text(
    filesystem: SecureDirectory,
    path: Path,
    size: int,
) -> str:
    descriptor = filesystem.open_file(path)
    try:
        before = os.fstat(descriptor)
        if before.st_size != size:
            raise SecureFileError(f"Static preflight source changed: {path}")
        payload = bytearray()
        remaining = size
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                raise SecureFileError(f"Static preflight source changed: {path}")
            payload.extend(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise SecureFileError(f"Static preflight source changed: {path}")
        after = os.fstat(descriptor)
        if (
            before.st_dev != after.st_dev
            or before.st_ino != after.st_ino
            or before.st_mode != after.st_mode
            or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
            or before.st_ctime_ns != after.st_ctime_ns
        ):
            raise SecureFileError(f"Static preflight source changed: {path}")
    finally:
        os.close(descriptor)
    return bytes(payload).decode("utf-8")


def _normalized_local_path(
    source: PurePosixPath,
    value: str,
) -> PurePosixPath | None:
    selected = unquote(urlsplit(value).path)
    if not selected:
        return source
    parts = list(source.parent.parts)
    for part in PurePosixPath(selected).parts:
        if part in {"", "."}:
            continue
        if part == "..":
            if not parts:
                return None
            parts.pop()
            continue
        parts.append(part)
    return PurePosixPath(*parts)


def _reference_issue(
    *,
    available: frozenset[PurePosixPath],
    source: PurePosixPath,
    value: str,
    line: int,
    column: int,
    module: bool,
    required: bool = True,
) -> StaticPreflightIssue | None:
    selected = value.strip()
    if not selected or selected.startswith("#"):
        return None
    location = SourceLocation(source, line, column)
    severity: Literal["warning", "error"] = "error" if required else "warning"
    try:
        parsed = urlsplit(selected)
    except ValueError as error:
        return StaticPreflightIssue(
            "static-reference-invalid",
            severity,
            f"Static browser reference {selected!r} is invalid: {error}",
            location,
            selected,
            "Use a valid browser URL.",
        )
    if (
        len(selected) >= 3
        and selected[0].isalpha()
        and selected[1] == ":"
        and selected[2] in "\\/"
    ):
        return StaticPreflightIssue(
            "static-file-path",
            severity,
            f"Static browser code references build-machine path {selected!r}.",
            location,
            selected,
            "Bundle the dependency into the view artifact and use a relative URL.",
        )
    if parsed.scheme.casefold() == "file":
        return StaticPreflightIssue(
            "static-file-url",
            severity,
            f"Static browser code references a build-machine file URL: {selected!r}.",
            location,
            selected,
            "Bundle the dependency into the view artifact and use a relative URL.",
        )
    if parsed.scheme:
        if module and parsed.scheme.casefold() not in _REMOTE_SCHEMES:
            return StaticPreflightIssue(
                "static-module-scheme",
                "error",
                f"Browser module reference {selected!r} uses an unavailable scheme.",
                location,
                selected,
                "Bundle the module or use an explicit HTTP or HTTPS dependency.",
            )
        return None
    if parsed.netloc:
        return None
    if parsed.path.startswith(("/", "\\")):
        return StaticPreflightIssue(
            "static-root-absolute-url",
            severity,
            f"Static browser code uses root-absolute URL {selected!r}.",
            location,
            selected,
            "Use a document-relative URL so the export remains relocatable.",
        )
    if module and not parsed.path.startswith(("./", "../")):
        return StaticPreflightIssue(
            "static-bare-module",
            "warning",
            f"Static browser code retains bare module specifier {selected!r}.",
            location,
            selected,
            "Verify the document resolves this specifier through an import map.",
        )
    target = _normalized_local_path(source, selected)
    if target is None:
        return StaticPreflightIssue(
            "static-reference-outside-bundle",
            severity,
            f"Static browser reference {selected!r} leaves the exported directory.",
            location,
            selected,
            "Keep browser dependencies inside the exported directory.",
        )
    candidates = (
        (target, target / "index.html") if parsed.path.endswith("/") else (target,)
    )
    if not any(candidate in available for candidate in candidates):
        return StaticPreflightIssue(
            "static-reference-missing" if required else "static-url-target-missing",
            severity,
            (
                f"Static browser reference {selected!r} has no exported file."
                if required
                else f"Static URL target {selected!r} has no exported file."
            ),
            location,
            selected,
            (
                "Include the referenced file in the provider artifact or update "
                "the URL."
                if required
                else (
                    "Include this target when runtime code can load it, or verify "
                    "that the constructed URL remains inert."
                )
            ),
        )
    return None


def _javascript_issues(
    source_path: PurePosixPath,
    source: str,
    available: frozenset[PurePosixPath],
) -> tuple[list[StaticPreflightIssue], int]:
    issues: list[StaticPreflightIssue] = []
    references = 0
    for dependency in javascript_dependencies(source):
        line, column = _position(source, dependency.offset)
        location = SourceLocation(source_path, line, column)
        if dependency.kind == "parse error":
            issues.append(
                StaticPreflightIssue(
                    "static-module-uninspected",
                    "warning",
                    (
                        "Static preflight could not inspect part of this "
                        "JavaScript module."
                    ),
                    location,
                    hint="Inspect this emitted module before publishing the export.",
                )
            )
            continue
        if dependency.specifier is None:
            issues.append(
                StaticPreflightIssue(
                    "static-module-computed",
                    "warning",
                    f"Static preflight cannot resolve this {dependency.kind}.",
                    location,
                    hint=(
                        "Verify the computed module target is available after "
                        "publication."
                    ),
                )
            )
            continue
        if dependency.specifier == TRUNCATED_SPECIFIER:
            issues.append(
                StaticPreflightIssue(
                    "static-module-specifier-too-large",
                    "error",
                    "Static browser code contains an oversized module specifier.",
                    location,
                    hint="Use a bounded module URL.",
                )
            )
            continue
        references += 1
        url_constructor = dependency.kind == "import meta URL"
        issue = _reference_issue(
            available=available,
            source=source_path,
            value=dependency.specifier,
            line=line,
            column=column,
            module=not url_constructor,
            required=not url_constructor,
        )
        if issue is not None:
            issues.append(issue)
    return issues, references


def _html_issues(
    source_path: PurePosixPath,
    source: str,
    available: frozenset[PurePosixPath],
) -> tuple[list[StaticPreflightIssue], int]:
    parser = HTMLDocumentParser()
    parser.feed(source)
    issues: list[StaticPreflightIssue] = []
    references = 0
    for resource in parser.resources:
        references += 1
        line, column = resource.position
        issue = _reference_issue(
            available=available,
            source=source_path,
            value=resource.value,
            line=line,
            column=column,
            module=False,
        )
        if issue is not None:
            issues.append(issue)
    for script in parser.inline_scripts:
        script_issues, script_references = _javascript_issues(
            source_path,
            script.content,
            available,
        )
        start_line, start_column = script.position
        for issue in script_issues:
            line = start_line + issue.source.line - 1
            column = (
                start_column + issue.source.column - 1
                if issue.source.line == 1
                else issue.source.column
            )
            issues.append(
                replace(issue, source=SourceLocation(source_path, line, column))
            )
        references += script_references
    return issues, references


def _css_issues(
    source_path: PurePosixPath,
    source: str,
    available: frozenset[PurePosixPath],
) -> tuple[list[StaticPreflightIssue], int]:
    issues: list[StaticPreflightIssue] = []
    resources = css_resource_urls(source)
    for value, offset in resources:
        line, column = _position(source, offset)
        issue = _reference_issue(
            available=available,
            source=source_path,
            value=value,
            line=line,
            column=column,
            module=False,
        )
        if issue is not None:
            issues.append(issue)
    return issues, len(resources)


def preflight_static_bundle(
    filesystem: SecureDirectory,
    *,
    view: str,
    runtime: StaticRuntime,
    document: PurePosixPath,
    projections: tuple[ProjectionPortability, ...],
) -> StaticPreflightReport:
    """Verify local browser references in the exact staged export tree."""
    inventory = filesystem.regular_file_sizes(
        max_entries=ARTIFACT_OUTPUT_BUDGET.max_files,
    )
    sizes = {
        PurePosixPath(path.relative_to(filesystem.root).as_posix()): size
        for path, size in inventory
    }
    available = frozenset(sizes)
    issues: list[StaticPreflightIssue] = []
    inspected_files = 0
    references = 0
    consumed_bytes = 0
    if document not in available:
        issues.append(
            StaticPreflightIssue(
                "static-document-missing",
                "error",
                f"Static entry document {document.as_posix()!r} is unavailable.",
                SourceLocation(document, 1, 1),
                hint="Rebuild the provider artifact and rerun the export.",
            )
        )
    selected_files = tuple(
        sorted(
            path
            for path in available
            if path.suffix.casefold() in _TEXT_SUFFIXES
            and path.parts[0] != "_marimo-studio"
        )
    )
    for relative in selected_files:
        size = sizes[relative]
        if size > _MAX_TEXT_FILE_BYTES or consumed_bytes + size > _MAX_TEXT_TOTAL_BYTES:
            issues.append(
                StaticPreflightIssue(
                    "static-source-uninspected",
                    "warning",
                    (
                        "Static preflight skipped large browser source "
                        f"{relative.as_posix()!r}."
                    ),
                    SourceLocation(relative, 1, 1),
                    hint="Inspect this emitted file before publishing the export.",
                )
            )
            continue
        try:
            source = _read_text(filesystem, filesystem.root / relative, size)
        except (OSError, UnicodeError, SecureFileError) as error:
            issues.append(
                StaticPreflightIssue(
                    "static-source-unreadable",
                    "error",
                    f"Static preflight could not read {relative.as_posix()!r}: {error}",
                    SourceLocation(relative, 1, 1),
                    hint="Rebuild the provider artifact and rerun the export.",
                )
            )
            continue
        inspected_files += 1
        consumed_bytes += size
        suffix = relative.suffix.casefold()
        if suffix in {".html", ".htm"}:
            found, count = _html_issues(relative, source, available)
        elif suffix == ".css":
            found, count = _css_issues(relative, source, available)
        else:
            found, count = _javascript_issues(relative, source, available)
        issues.extend(found)
        references += count
    filesystem.ensure_attached()
    return StaticPreflightReport(
        view=view,
        runtime=runtime,
        document=document,
        files=len(inventory),
        browser_files=len(selected_files),
        inspected_files=inspected_files,
        references=references,
        projections=projections,
        issues=tuple(
            sorted(
                set(issues),
                key=lambda item: (
                    item.source.path.as_posix(),
                    item.source.line,
                    item.source.column,
                    item.code,
                    item.reference or "",
                ),
            )
        ),
    )


__all__ = [
    "StaticPreflightIssue",
    "StaticPreflightReport",
    "preflight_static_bundle",
]
