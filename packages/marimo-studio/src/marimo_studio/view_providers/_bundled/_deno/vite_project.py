"""Build an inspected frontend project with the contained Vite toolchain."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

from marimo_studio.view_providers import BuildRequest, BuildResult, ProjectDiagnostic
from marimo_studio.view_providers._bundled import _deno
from marimo_studio.view_providers._bundled._deno.analysis import apply_instrumentation
from marimo_studio.view_providers._bundled._deno.project import (
    ProviderProjectSpec,
    copy_public_assets,
    failure,
)
from marimo_studio.view_providers._bundled._deno.vite import (
    ViteBuildPaths,
    build_vite,
    install_dependencies,
    validate_install_manifests,
)

SourceCheck = Callable[
    [BuildRequest, Path, ViteBuildPaths, _deno.DenoExecution],
    tuple[ProjectDiagnostic, ...],
]


class _BuildStepError(Exception):
    def __init__(self, diagnostic: ProjectDiagnostic) -> None:
        super().__init__(diagnostic.message)
        self.diagnostic = diagnostic


@contextmanager
def _build_step(label: str, code: str, operation: str) -> Iterator[None]:
    try:
        yield
    except (OSError, ValueError) as error:
        raise _BuildStepError(failure(label, code, operation, str(error))) from error


def _build_project(
    request: BuildRequest,
    spec: ProviderProjectSpec,
    execution: _deno.DenoExecution,
    *,
    vite_version: str,
    label: str,
    code_prefix: str,
    check: SourceCheck | None = None,
) -> BuildResult:
    """Install, check, instrument, and build one inspected Vite project."""
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
                    message=(
                        f"{label} projection sites changed before the build started."
                    ),
                ),
            ),
        )
    work = request.staging_root.parent / "work"
    with _build_step(label, f"{code_prefix}-staging-failed", "stage source"):
        paths = ViteBuildPaths(
            entrypoint=spec.option_path(request.project, "entrypoint"),
            config=spec.option_path(request.project, "config"),
            lockfile=spec.option_path(request.project, "lockfile"),
            vite_config=spec.option_path(request.project, "vite_config"),
        )
        if paths.entrypoint.name != "index.html":
            raise ValueError(f"{label} entrypoint must be named index.html")
        _deno.copy_project_inputs(
            request.project,
            request.inputs,
            work,
            request.cancellation,
        )
    with _build_step(
        label, f"{code_prefix}-dependencies-invalid", "validate exact dependencies"
    ):
        validate_install_manifests(work, paths)
    diagnostic = install_dependencies(
        request, work, paths, execution, label=label, code_prefix=code_prefix
    )
    if diagnostic is not None:
        return BuildResult(None, (diagnostic,))
    check_diagnostics = (
        check(request, work, paths, execution) if check is not None else ()
    )
    if any(item.severity == "error" for item in check_diagnostics):
        return BuildResult(None, check_diagnostics)
    with _build_step(
        label, f"{code_prefix}-instrumentation-failed", "instrument projection sites"
    ):
        apply_instrumentation(work, analysis.edits)
    with _build_step(
        label, f"{code_prefix}-staging-failed", "bound workspace discovery"
    ):
        (work / "pnpm-workspace.yaml").write_text("packages: []\n", encoding="utf-8")
    diagnostic = build_vite(
        request,
        work,
        vite_version,
        paths,
        execution,
        label=label,
        code_prefix=code_prefix,
    )
    if diagnostic is not None:
        return BuildResult(None, (diagnostic,))
    with _build_step(
        label, f"{code_prefix}-public-assets-invalid", "publish public assets"
    ):
        copy_public_assets(
            work, request.staging_root, cancellation=request.cancellation
        )
    return BuildResult(PurePosixPath("index.html"), check_diagnostics)


def build_vite_project(
    request: BuildRequest,
    spec: ProviderProjectSpec,
    *,
    vite_version: str,
    label: str,
    code_prefix: str,
    check: SourceCheck | None = None,
) -> BuildResult:
    """Install, check, instrument, and build one inspected Vite project."""
    try:
        execution = _deno.create_execution(
            request.project,
            cache_root=request.cache_root,
            cancellation=request.cancellation,
            runner=request.runner,
        )
        return _build_project(
            request,
            spec,
            execution,
            vite_version=vite_version,
            label=label,
            code_prefix=code_prefix,
            check=check,
        )
    except _BuildStepError as error:
        return BuildResult(None, (error.diagnostic,))
    except _deno.DenoExecutionError as error:
        return BuildResult(
            None,
            (
                failure(
                    label,
                    f"{code_prefix}-build-failed",
                    "finish the build",
                    str(error),
                ),
            ),
        )
