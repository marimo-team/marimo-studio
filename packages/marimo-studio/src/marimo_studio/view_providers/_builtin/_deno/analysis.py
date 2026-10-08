"""Normalize provider analyzer output into projection-site records."""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources
from pathlib import PurePosixPath
from typing import cast

from marimo_studio.view_providers import (
    ProjectDiagnostic,
    ProjectionKind,
    ProjectionSite,
    SourceLocation,
    ViewProject,
    parse_accept,
    project_path,
)
from marimo_studio.view_providers._builtin import _deno
from marimo_studio.view_providers._builtin._deno.runtime import permission_paths

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
class SourceAnalysis:
    """Projection sites and diagnostics from one analyzer."""

    sites: tuple[ProjectionSite, ...]
    diagnostics: tuple[ProjectDiagnostic, ...]


def _analysis_failure(message: str) -> SourceAnalysis:
    return SourceAnalysis(
        (),
        (
            ProjectDiagnostic(
                code="provider-analysis-failed",
                severity="error",
                message=message,
                hint=_deno.DOWNLOAD_FAILURE_HINT
                if _deno.download_failed(message)
                else "",
            ),
        ),
    )


def tool_source_path(value: object) -> PurePosixPath:
    if not isinstance(value, str):
        raise ValueError("Provider analyzer path must be a string")
    return project_path(value.replace("\\", "/"), field="Provider analyzer path")


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
    analyzer_package: str,
    paths: tuple[PurePosixPath, ...],
    lockfile: PurePosixPath,
    execution: _deno.DenoExecution,
) -> SourceAnalysis:
    """Run a packaged Deno analyzer and normalize its JSON result."""
    script = resources.files(analyzer_package).joinpath("analyzer.ts")
    with resources.as_file(script) as script_path:
        shared_analyzers = script_path.parent.parent / "_deno" / "analyzers"
        read_paths = permission_paths(
            project.root, script_path.parent, shared_analyzers
        )
        try:
            result = execution.run(
                (
                    "run",
                    "--no-prompt",
                    "--no-config",
                    f"--lock={project.root.joinpath(*lockfile.parts)}",
                    "--frozen",
                    "--node-modules-dir=none",
                    f"--allow-read={read_paths}",
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
    if not isinstance(payload, dict) or payload.get("schema") != 1:
        return _analysis_failure("Provider analyzer returned an unsupported schema")
    try:
        diagnostics = tuple(
            _diagnostic(item) for item in payload.get("diagnostics", [])
        )
    except ValueError as error:
        return _analysis_failure(str(error))
    sites: list[ProjectionSite] = []
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
        raw_targets = raw.get("targets")
        raw_accept = raw.get("accept")
        try:
            accept = parse_accept(kind, raw_accept)
        except (TypeError, ValueError) as error:
            diagnostics = (
                *diagnostics,
                ProjectDiagnostic(
                    "projection-accept-invalid",
                    "error",
                    f"The accept attribute is invalid: {error}.",
                    'List image types, such as accept="image/svg+xml image/png".',
                    SourceLocation(path, line, column),
                ),
            )
            continue
        site = ProjectionSite(
            kind=kind,
            targets=(
                "*"
                if raw_targets is None
                else tuple(cast(list[str], raw_targets))
                if isinstance(raw_targets, list)
                else ()
            ),
            source=SourceLocation(path, line, column),
            offset=offset,
            accept=accept,
        )
        sites.append(site)
    return SourceAnalysis(tuple(sites), diagnostics)
