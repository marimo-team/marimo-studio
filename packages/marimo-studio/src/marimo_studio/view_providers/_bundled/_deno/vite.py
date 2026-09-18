"""Install locked npm projects and run Vite inside the Deno build boundary."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from marimo_studio.view_providers import BuildRequest, ProjectDiagnostic
from marimo_studio.view_providers._bundled import _deno
from marimo_studio.view_providers._bundled._deno.project import command, failure
from marimo_studio.view_providers._bundled._deno.runtime import permission_paths


@dataclass(frozen=True)
class ViteBuildPaths:
    """Project-relative inputs used by the contained Vite toolchain."""

    entrypoint: PurePosixPath
    config: PurePosixPath
    lockfile: PurePosixPath
    vite_config: PurePosixPath


_EXACT_NPM_VERSION = re.compile(
    r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)
_DEPENDENCY_TABLES = (
    "dependencies",
    "devDependencies",
    "optionalDependencies",
    "peerDependencies",
)


def _read_json(path: Path, label: str) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} must be valid UTF-8 JSON: {error}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return payload


def validate_install_manifests(work: Path, paths: ViteBuildPaths) -> None:
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


def _build_read_paths(work: Path, output: Path) -> tuple[Path, ...]:
    ldd = Path("/usr/bin/ldd")
    if ldd.is_file():
        return (work, output, ldd)
    return (work, output)


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


def install_dependencies(
    request: BuildRequest,
    work: Path,
    paths: ViteBuildPaths,
    execution: _deno.DenoExecution,
    *,
    label: str,
    code_prefix: str,
) -> ProjectDiagnostic | None:
    installed, diagnostic = command(
        label,
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
        code=f"{code_prefix}-install-failed",
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
        label,
        f"{code_prefix}-install-failed",
        "install locked dependencies",
        installed.stderr,
    )


def build_vite(
    request: BuildRequest,
    work: Path,
    version: str,
    paths: ViteBuildPaths,
    execution: _deno.DenoExecution,
    *,
    label: str,
    code_prefix: str,
) -> ProjectDiagnostic | None:
    try:
        bindings = _native_bindings(work, request.profile)
    except (OSError, ValueError) as error:
        return failure(
            label,
            f"{code_prefix}-native-dependency-invalid",
            "load locked native dependencies",
            str(error),
        )
    output = request.staging_root.resolve()
    arguments = [
        "run",
        "--cached-only",
        "--no-remote",
        "--deny-import",
        f"--allow-read={permission_paths(*_build_read_paths(work, output))}",
        f"--allow-write={permission_paths(output)}",
        "--allow-env",
        "--allow-sys=uid,osRelease",
        f"--allow-ffi={permission_paths(*bindings)}",
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
        label,
        request.project,
        arguments,
        cwd=work,
        code=f"{code_prefix}-build-failed",
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
        label,
        f"{code_prefix}-build-failed",
        "build source",
        built.stderr,
    )
