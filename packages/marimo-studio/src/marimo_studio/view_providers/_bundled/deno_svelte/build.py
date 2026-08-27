"""Build an inspected Svelte project into a Studio staging directory."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from marimo_studio.view_providers import (
    BuildRequest,
    BuildResult,
    ProjectDiagnostic,
    SourceLocation,
)
from marimo_studio.view_providers._bundled import _deno
from marimo_studio.view_providers._bundled._deno.analysis import (
    apply_instrumentation,
    tool_source_path,
)
from marimo_studio.view_providers._bundled._deno.project import (
    ProviderProjectSpec,
    command,
    copy_public_assets,
    failure,
)
from marimo_studio.view_providers._validation import validate_relative_path

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
_EXACT_NPM_VERSION = re.compile(
    r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)
_DEPENDENCY_TABLES = (
    "dependencies",
    "devDependencies",
    "optionalDependencies",
    "peerDependencies",
)


def _check_code(value: object) -> str:
    tokens = re.findall(r"[a-z0-9]+", str(value).casefold())
    if not tokens:
        return "svelte-check"
    normalized = "-".join(tokens)
    if normalized == "svelte-check" or normalized.startswith("svelte-check-"):
        return normalized
    return f"svelte-check-{normalized}"


@dataclass(frozen=True)
class _BuildPaths:
    entrypoint: PurePosixPath
    config: PurePosixPath
    lockfile: PurePosixPath
    vite_config: PurePosixPath
    svelte_config: PurePosixPath
    tsconfig: PurePosixPath


def _build_paths(request: BuildRequest) -> _BuildPaths:
    options = request.project.options
    entrypoint = validate_relative_path(
        options.get("entrypoint", "src/index.html"),
        field="Svelte entrypoint",
    )
    if entrypoint.name != "index.html":
        raise ValueError("Svelte entrypoint must be named index.html")
    return _BuildPaths(
        entrypoint=entrypoint,
        config=validate_relative_path(
            options.get("config", "deno.json"), field="Svelte Deno config"
        ),
        lockfile=validate_relative_path(
            options.get("lockfile", "deno.lock"), field="Svelte lockfile"
        ),
        vite_config=validate_relative_path(
            options.get("vite_config", "vite.config.ts"), field="Svelte Vite config"
        ),
        svelte_config=PurePosixPath("svelte.config.js"),
        tsconfig=validate_relative_path(
            options.get("tsconfig", "tsconfig.json"), field="Svelte TypeScript config"
        ),
    )


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


def _read_json(path: Path, label: str) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} must be valid UTF-8 JSON: {error}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return payload


def _validate_install_manifests(work: Path, paths: _BuildPaths) -> None:
    deno_config = _read_json(
        work.joinpath(*paths.config.parts),
        paths.config.as_posix(),
    )
    forbidden_deno = tuple(
        name for name in ("allowScripts", "workspace", "links") if name in deno_config
    )
    if forbidden_deno:
        raise ValueError(
            f"{paths.config.as_posix()} cannot declare {forbidden_deno[0]}"
        )
    package_path = work / "package.json"
    package = _read_json(package_path, "package.json")
    if "workspaces" in package:
        raise ValueError("package.json cannot declare workspaces")
    for table_name in _DEPENDENCY_TABLES:
        table = package.get(table_name, {})
        if not isinstance(table, dict):
            raise ValueError(f"package.json {table_name} must be an object")
        for name, version in table.items():
            if not isinstance(name, str) or not isinstance(version, str):
                raise ValueError(
                    f"package.json {table_name} entries must be string pairs"
                )
            if _EXACT_NPM_VERSION.fullmatch(version) is None:
                raise ValueError(
                    f"package.json dependency {name!r} must use an exact npm version"
                )


def _permission_paths(*paths: Path) -> str:
    return ",".join(str(path.resolve()) for path in paths)


def _native_bindings(work: Path, profile: str) -> tuple[Path, ...]:
    dependency_root = (work / "node_modules" / ".deno").resolve()
    selected: list[Path] = []
    for path in sorted(dependency_root.rglob("*.node")):
        resolved = path.resolve()
        try:
            relative = resolved.relative_to(dependency_root)
        except ValueError as error:
            raise ValueError(
                f"Native dependency escapes node_modules: {path}"
            ) from error
        encoded = relative.as_posix()
        if "@rolldown+binding-" in encoded or (
            profile == "production" and encoded.startswith("lightningcss-")
        ):
            selected.append(resolved)
    if not any("@rolldown+binding-" in path.as_posix() for path in selected):
        raise ValueError("The locked Rolldown native binding is unavailable")
    if profile == "production" and not any(
        "lightningcss-" in path.as_posix() for path in selected
    ):
        raise ValueError("The locked Lightning CSS native binding is unavailable")
    return tuple(selected)


def _run_install(
    request: BuildRequest,
    work: Path,
    paths: _BuildPaths,
    execution: _deno.DenoExecution,
) -> ProjectDiagnostic | None:
    installed, diagnostic = command(
        _LABEL,
        request.project,
        (
            "install",
            f"--config={paths.config.as_posix()}",
            f"--lock={paths.lockfile.as_posix()}",
            "--frozen",
            "--node-modules-dir=auto",
            "--no-save",
        ),
        cwd=work,
        code="svelte-install-failed",
        operation="install locked dependencies",
        execution=execution,
        network_environment=True,
    )
    if diagnostic is not None:
        return diagnostic
    assert installed is not None
    if installed.returncode == 0:
        return None
    return failure(
        _LABEL,
        "svelte-install-failed",
        "install locked dependencies",
        installed.stderr,
    )


def _run_check(
    request: BuildRequest,
    work: Path,
    version: str,
    paths: _BuildPaths,
    execution: _deno.DenoExecution,
) -> tuple[tuple[ProjectDiagnostic, ...], ProjectDiagnostic | None]:
    checked, diagnostic = command(
        _LABEL,
        request.project,
        (
            "run",
            "--cached-only",
            "--no-remote",
            "--deny-import",
            f"--allow-read={work.resolve()}",
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
            paths.tsconfig.as_posix(),
            "--config",
            paths.svelte_config.as_posix(),
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
        return (), diagnostic
    assert checked is not None
    diagnostics = _check_diagnostics(checked.stdout)
    if checked.returncode == 0:
        return diagnostics, None
    if diagnostics:
        first_error = next(
            (item for item in diagnostics if item.severity == "error"),
            None,
        )
        if first_error is not None:
            return diagnostics, first_error
    return (), failure(
        _LABEL,
        "svelte-check-failed",
        "check source",
        checked.stderr or checked.stdout,
    )


def _run_build(
    request: BuildRequest,
    work: Path,
    version: str,
    paths: _BuildPaths,
    execution: _deno.DenoExecution,
) -> ProjectDiagnostic | None:
    try:
        bindings = _native_bindings(work, request.profile)
    except (OSError, ValueError) as error:
        return failure(
            _LABEL,
            "svelte-native-dependency-invalid",
            "load locked native dependencies",
            str(error),
        )
    output = request.staging_root.resolve()
    arguments = [
        "run",
        "--cached-only",
        "--no-remote",
        "--deny-import",
        f"--allow-read={_permission_paths(work, output)}",
        f"--allow-write={output}",
        "--allow-env",
        f"--allow-ffi={_permission_paths(*bindings)}",
        "--no-prompt",
        f"--config={paths.config.as_posix()}",
        f"--lock={paths.lockfile.as_posix()}",
        "--frozen",
        "--node-modules-dir=manual",
        f"npm:vite@{version}",
        "build",
        paths.entrypoint.parent.as_posix(),
        "--config",
        paths.vite_config.as_posix(),
        "--configLoader",
        "native",
        "--base",
        "./",
        "--outDir",
        str(request.staging_root),
        "--emptyOutDir",
    ]
    if request.profile == "development":
        arguments.extend(("--mode", "development", "--sourcemap", "--minify=false"))
    else:
        arguments.extend(("--mode", "production"))
    built, diagnostic = command(
        _LABEL,
        request.project,
        arguments,
        cwd=work,
        code="svelte-build-failed",
        operation="build source",
        execution=execution,
        environment={
            "NODE_ENV": "production",
            "TMPDIR": str(work.resolve()),
            "TEMP": str(work.resolve()),
            "TMP": str(work.resolve()),
        },
    )
    if diagnostic is not None:
        return diagnostic
    assert built is not None
    if built.returncode == 0:
        return None
    return failure(
        _LABEL,
        "svelte-build-failed",
        "build source",
        built.stderr,
    )


def _build_svelte(
    request: BuildRequest,
    spec: ProviderProjectSpec,
    execution: _deno.DenoExecution,
    *,
    svelte_check_version: str,
    vite_version: str,
) -> BuildResult:
    """Install, check, instrument, and build one Svelte project."""
    try:
        analysis = spec.analyze(
            request.project,
            request.inspection,
            execution,
        )
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
    if analysis.diagnostics:
        return BuildResult(None, analysis.diagnostics)
    if analysis.sites != request.inspection.mounts:
        return BuildResult(
            None,
            (
                ProjectDiagnostic(
                    code="projection-sites-changed",
                    severity="error",
                    message="Svelte projection sites changed before the build started.",
                ),
            ),
        )
    work = request.staging_root.parent / "work"
    try:
        paths = _build_paths(request)
        _deno.copy_project_inputs(
            request.project,
            request.inputs,
            work,
            request.cancellation,
        )
    except (OSError, ValueError) as error:
        return BuildResult(
            None,
            (failure(_LABEL, "svelte-staging-failed", "stage source", str(error)),),
        )
    try:
        _validate_install_manifests(work, paths)
    except ValueError as error:
        return BuildResult(
            None,
            (
                failure(
                    _LABEL,
                    "svelte-dependencies-invalid",
                    "validate exact dependencies",
                    str(error),
                ),
            ),
        )
    diagnostic = _run_install(request, work, paths, execution)
    if diagnostic is not None:
        return BuildResult(None, (diagnostic,))
    check_diagnostics, diagnostic = _run_check(
        request,
        work,
        svelte_check_version,
        paths,
        execution,
    )
    if diagnostic is not None:
        return BuildResult(None, check_diagnostics or (diagnostic,))
    try:
        apply_instrumentation(work, analysis.edits)
    except (OSError, ValueError) as error:
        return BuildResult(
            None,
            (
                failure(
                    _LABEL,
                    "svelte-instrumentation-failed",
                    "instrument projection sites",
                    str(error),
                ),
            ),
        )
    try:
        (work / "pnpm-workspace.yaml").write_text(
            "packages: []\n",
            encoding="utf-8",
        )
    except OSError as error:
        return BuildResult(
            None,
            (
                failure(
                    _LABEL,
                    "svelte-staging-failed",
                    "bound workspace discovery",
                    str(error),
                ),
            ),
        )
    diagnostic = _run_build(request, work, vite_version, paths, execution)
    if diagnostic is not None:
        return BuildResult(None, (diagnostic,))
    try:
        copy_public_assets(
            work,
            request.staging_root,
            cancellation=request.cancellation,
        )
    except (OSError, ValueError) as error:
        return BuildResult(
            None,
            (
                failure(
                    _LABEL,
                    "svelte-public-assets-invalid",
                    "publish public assets",
                    str(error),
                ),
            ),
        )
    return BuildResult(PurePosixPath("index.html"), check_diagnostics)


def build_svelte(
    request: BuildRequest,
    spec: ProviderProjectSpec,
    *,
    svelte_check_version: str,
    vite_version: str,
) -> BuildResult:
    """Install, check, instrument, and build one Svelte project."""
    try:
        execution = _deno.create_execution(
            request.project,
            cache_root=request.cache_root,
            cancellation=request.cancellation,
            runner=request.runner,
        )
        return _build_svelte(
            request,
            spec,
            execution,
            svelte_check_version=svelte_check_version,
            vite_version=vite_version,
        )
    except _deno.DenoExecutionError as error:
        return BuildResult(
            None,
            (
                failure(
                    _LABEL,
                    "svelte-build-failed",
                    "finish the build",
                    str(error),
                ),
            ),
        )
