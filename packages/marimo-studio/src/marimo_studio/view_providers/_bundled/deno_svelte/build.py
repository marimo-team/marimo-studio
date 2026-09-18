"""Build an inspected Svelte project into a Studio staging directory."""

from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath

from marimo_studio.view_providers import (
    BuildRequest,
    BuildResult,
    ProjectDiagnostic,
    SourceLocation,
)
from marimo_studio.view_providers._bundled import _deno
from marimo_studio.view_providers._bundled._deno.analysis import tool_source_path
from marimo_studio.view_providers._bundled._deno.project import (
    ProviderProjectSpec,
    command,
    failure,
)
from marimo_studio.view_providers._bundled._deno.runtime import permission_paths
from marimo_studio.view_providers._bundled._deno.vite import ViteBuildPaths
from marimo_studio.view_providers._bundled._deno.vite_project import build_vite_project

_LABEL = "Svelte provider"
_IGNORED_CHECK_ENVIRONMENT = ",".join(
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
        "XDG_RUNTIME_DIR",
        "VSCODE_NLS_CONFIG",
    )
)


def _check_code(value: object) -> str:
    tokens = re.findall(r"[a-z0-9]+", str(value).casefold())
    if not tokens:
        return "svelte-check"
    normalized = "-".join(tokens)
    if normalized == "svelte-check" or normalized.startswith("svelte-check-"):
        return normalized
    return f"svelte-check-{normalized}"


def _json_check_diagnostic(raw: str) -> ProjectDiagnostic | None:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    severity = payload.get("type")
    start = payload.get("start")
    filename = payload.get("filename")
    if (
        severity not in {"ERROR", "WARNING"}
        or not isinstance(start, dict)
        or not isinstance(filename, str)
    ):
        return None
    return ProjectDiagnostic(
        code=_check_code(payload.get("code", "svelte-check")),
        severity="error" if severity == "ERROR" else "warning",
        message=str(payload.get("message", "Svelte check failed")),
        source=SourceLocation(
            tool_source_path(filename),
            int(start.get("line", 0)) + 1,
            int(start.get("character", 0)) + 1,
        ),
    )


def _check_diagnostics(output: str) -> tuple[ProjectDiagnostic, ...]:
    diagnostics: list[ProjectDiagnostic] = []
    for line in output.splitlines():
        _, separator, payload = line.partition(" ")
        diagnostic = (
            _json_check_diagnostic(payload)
            if separator and payload.startswith("{")
            else None
        )
        if diagnostic is not None:
            diagnostics.append(diagnostic)
    return tuple(diagnostics)


def _run_check(
    request: BuildRequest,
    work: Path,
    paths: ViteBuildPaths,
    execution: _deno.DenoExecution,
    *,
    version: str,
    tsconfig: PurePosixPath,
) -> tuple[ProjectDiagnostic, ...]:
    checked, diagnostic = command(
        _LABEL,
        request.project,
        (
            "run",
            "--cached-only",
            "--no-remote",
            "--deny-import",
            f"--allow-read={permission_paths(work)}",
            f"--ignore-env={_IGNORED_CHECK_ENVIRONMENT}",
            "--no-prompt",
            f"--config={paths.config.as_posix()}",
            f"--lock={paths.lockfile.as_posix()}",
            "--frozen",
            "--node-modules-dir=manual",
            f"npm:svelte-check@{version}",
            "--workspace",
            ".",
            "--tsconfig",
            tsconfig.as_posix(),
            "--config",
            "svelte.config.js",
            "--output",
            "machine-verbose",
            "--no-color",
        ),
        cwd=work,
        code="svelte-check-failed",
        operation="check source",
        execution=execution,
    )
    if diagnostic is not None:
        return (diagnostic,)
    assert checked is not None
    diagnostics = _check_diagnostics(checked.stdout)
    if checked.returncode == 0:
        return diagnostics
    if diagnostics:
        first_error = next(
            (item for item in diagnostics if item.severity == "error"),
            None,
        )
        if first_error is not None:
            return diagnostics
    return (
        failure(
            _LABEL,
            "svelte-check-failed",
            "check source",
            checked.stderr or checked.stdout,
        ),
    )


def build_svelte(
    request: BuildRequest,
    spec: ProviderProjectSpec,
    *,
    svelte_check_version: str,
    vite_version: str,
) -> BuildResult:
    """Check Svelte source and build one contained Vite candidate."""
    try:
        tsconfig = spec.option_path(request.project, "tsconfig")
    except ValueError as error:
        return BuildResult(
            None,
            (
                ProjectDiagnostic(
                    code="provider-options-invalid",
                    severity="error",
                    message=str(error),
                ),
            ),
        )
    return build_vite_project(
        request,
        spec,
        vite_version=vite_version,
        label=_LABEL,
        code_prefix="svelte",
        check=lambda request, work, paths, execution: _run_check(
            request,
            work,
            paths,
            execution,
            version=svelte_check_version,
            tsconfig=tsconfig,
        ),
    )
