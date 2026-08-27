"""Normalize provider analyzer output into projection-site records."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from importlib import resources
from pathlib import Path, PurePosixPath
from typing import cast

from marimo_studio.view_providers import (
    MountDeclaration,
    ProjectDiagnostic,
    ProjectionKind,
    SourceLocation,
    ViewProject,
    mount_attribute,
)
from marimo_studio.view_providers._bundled import _deno
from marimo_studio.view_providers._validation import validate_relative_path

_TYPESCRIPT_ENVIRONMENT = ",".join(
    (
        "TSC_WATCHFILE",
        "TSC_WATCHDIRECTORY",
        "TSC_NONPOLLING_WATCHER",
        "TSC_WATCH_POLLINGINTERVAL_LOW",
        "TSC_WATCH_POLLINGINTERVAL_MEDIUM",
        "TSC_WATCH_POLLINGINTERVAL_HIGH",
        "TSC_WATCH_POLLINGCHUNKSIZE_LOW",
        "TSC_WATCH_POLLINGCHUNKSIZE_MEDIUM",
        "TSC_WATCH_POLLINGCHUNKSIZE_HIGH",
        "TSC_WATCH_UNCHANGEDPOLLTHRESHOLDS_LOW",
        "TSC_WATCH_UNCHANGEDPOLLTHRESHOLDS_MEDIUM",
        "TSC_WATCH_UNCHANGEDPOLLTHRESHOLDS_HIGH",
        "NODE_INSPECTOR_IPC",
        "VSCODE_INSPECTOR_OPTIONS",
        "NODE_ENV",
    )
)


@dataclass(frozen=True)
class InstrumentationEdit:
    """Insert a projection site identifier at one source offset."""

    path: PurePosixPath
    offset: int
    text: str


@dataclass(frozen=True)
class SourceAnalysis:
    """Projection sites, diagnostics, and staging edits from one analyzer."""

    sites: tuple[MountDeclaration, ...]
    diagnostics: tuple[ProjectDiagnostic, ...]
    edits: tuple[InstrumentationEdit, ...]


def _analysis_failure(message: str) -> SourceAnalysis:
    return SourceAnalysis(
        (),
        (
            ProjectDiagnostic(
                code="provider-analysis-failed",
                severity="error",
                message=message,
            ),
        ),
        (),
    )


def _site_id(
    provider: str,
    path: PurePosixPath,
    kind: ProjectionKind,
    target: str | None,
    occurrence: int,
) -> str:
    identity = json.dumps(
        [provider, path.as_posix(), kind, target, occurrence],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"site-{hashlib.sha256(identity.encode()).hexdigest()}"


def tool_source_path(value: object) -> PurePosixPath:
    if not isinstance(value, str):
        raise ValueError("Provider analyzer path must be a string")
    return validate_relative_path(
        value.replace("\\", "/"),
        field="Provider analyzer path",
    )


def _diagnostic(raw: object) -> ProjectDiagnostic:
    if not isinstance(raw, dict):
        raise ValueError("Provider analyzer returned an invalid diagnostic")
    path = raw.get("path")
    line = raw.get("line")
    column = raw.get("column")
    source = None
    if isinstance(path, str) and isinstance(line, int) and isinstance(column, int):
        source = SourceLocation(tool_source_path(path), line, column)
    severity = raw.get("severity")
    if severity != "warning" and severity != "error":
        severity = "error"
    return ProjectDiagnostic(
        code=str(raw.get("code", "provider-analysis-failed")),
        severity=severity,
        message=str(raw.get("message", "Provider source analysis failed")),
        hint=str(raw.get("hint", "")),
        source=source,
    )


def analyze_sources(
    project: ViewProject,
    provider: str,
    analyzer_package: str,
    paths: tuple[PurePosixPath, ...],
    lockfile: PurePosixPath,
    execution: _deno.DenoExecution,
) -> SourceAnalysis:
    """Run a packaged Deno analyzer and normalize its JSON result."""
    script = resources.files(analyzer_package).joinpath("analyzer.ts")
    with resources.as_file(script) as script_path:
        shared_analyzers = script_path.parent.parent / "_deno" / "analyzers"
        try:
            result = execution.run(
                (
                    "run",
                    "--no-prompt",
                    "--no-config",
                    f"--lock={project.root.joinpath(*lockfile.parts)}",
                    "--frozen",
                    "--node-modules-dir=none",
                    f"--allow-read={project.root},{script_path.parent},{shared_analyzers}",
                    f"--allow-env={_TYPESCRIPT_ENVIRONMENT}",
                    str(script_path),
                    str(project.root),
                    *(path.as_posix() for path in paths),
                ),
                cwd=project.root,
                network_environment=True,
            )
        except _deno.DenoExecutionError as error:
            return _analysis_failure(str(error))
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip()
        return _analysis_failure(message or "Provider source analysis failed")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return _analysis_failure("Provider analyzer returned invalid JSON")
    if not isinstance(payload, dict) or payload.get("schema") != 2:
        return _analysis_failure("Provider analyzer returned an unsupported schema")
    try:
        diagnostics = tuple(
            _diagnostic(item) for item in payload.get("diagnostics", [])
        )
    except ValueError as error:
        return _analysis_failure(str(error))
    sites: list[MountDeclaration] = []
    edits: list[InstrumentationEdit] = []
    occurrences: dict[tuple[PurePosixPath, ProjectionKind, str | None], int] = {}
    for raw in payload.get("sites", []):
        if not isinstance(raw, dict):
            return _analysis_failure(
                "Provider analyzer returned an invalid projection site"
            )
        try:
            path = tool_source_path(raw["path"])
            kind = cast(ProjectionKind, raw["kind"])
            line = int(raw["line"])
            column = int(raw["column"])
            offset = int(raw["offset"])
        except (KeyError, TypeError, ValueError):
            return _analysis_failure(
                "Provider analyzer returned an incomplete projection site"
            )
        raw_targets = raw.get("allowedTargets")
        if raw_targets is not None and (
            not isinstance(raw_targets, list)
            or not raw_targets
            or any(
                not isinstance(target, str) or not target or target != target.strip()
                for target in raw_targets
            )
            or len(set(raw_targets)) != len(raw_targets)
        ):
            return _analysis_failure("Provider analyzer returned invalid mount targets")
        targets = (
            tuple(cast(list[str], raw_targets)) if raw_targets is not None else None
        )
        identity_target = (
            targets[0] if targets is not None and len(targets) == 1 else None
        )
        occurrence_key = (path, kind, identity_target)
        occurrence = occurrences.get(occurrence_key, 0)
        occurrences[occurrence_key] = occurrence + 1
        site_id = _site_id(provider, path, kind, identity_target, occurrence)
        sites.append(
            MountDeclaration(
                id=site_id,
                kind=kind,
                source=SourceLocation(path, line, column),
                allowed_targets=targets,
            )
        )
        attribute_name, attribute_value = mount_attribute(site_id)
        edits.append(
            InstrumentationEdit(
                path,
                offset,
                f' {attribute_name}="{attribute_value}"',
            )
        )
    return SourceAnalysis(tuple(sites), diagnostics, tuple(edits))


def apply_instrumentation(
    root: Path,
    edits: tuple[InstrumentationEdit, ...],
) -> None:
    """Apply source-site attributes to a disposable project copy."""
    grouped: dict[PurePosixPath, list[InstrumentationEdit]] = {}
    for edit in edits:
        grouped.setdefault(edit.path, []).append(edit)
    for relative, file_edits in grouped.items():
        path = root.joinpath(*relative.parts)
        content = path.read_bytes()
        parts: list[bytes] = []
        cursor = 0
        for edit in sorted(file_edits, key=lambda item: item.offset):
            if edit.offset < cursor or edit.offset > len(content):
                raise ValueError(f"Invalid instrumentation offset in {relative}")
            parts.extend((content[cursor : edit.offset], edit.text.encode()))
            cursor = edit.offset
        parts.append(content[cursor:])
        path.write_bytes(b"".join(parts))
