"""Compose provider project inspection, templates, and command diagnostics."""

from __future__ import annotations

import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from marimo_studio._artifacts.limits import (
    ARTIFACT_OUTPUT_BUDGET,
    PROJECT_INPUT_BUDGET,
    FileBudgetTracker,
)
from marimo_studio._filesystem.tree import bounded_regular_files
from marimo_studio._processes.provider_runner import ProviderCommandError
from marimo_studio.errors import ConfigurationError
from marimo_studio.view_providers import (
    InspectionRequest,
    ProjectDiagnostic,
    ProjectInput,
    ProjectInspection,
    ProviderAvailability,
    ProviderCancellation,
    ProviderCommandResult,
    SourceLocation,
    ViewProject,
)
from marimo_studio.view_providers._bundled import _deno
from marimo_studio.view_providers._bundled._deno.analysis import (
    SourceAnalysis,
    analyze_sources,
)
from marimo_studio.view_providers._validation import validate_relative_path

_DEFAULT_PUBLIC_ROOT = PurePosixPath("public")


@dataclass(frozen=True)
class ProviderProjectSpec:
    """Define one provider's durable file and analyzer contract."""

    provider_id: str
    analyzer_package: str
    input_scope: tuple[ProjectInput, ...]
    document_roots: tuple[PurePosixPath, ...]
    required_files: tuple[str, ...]
    editor_languages: Mapping[str, str]
    read_only: frozenset[str]
    option_paths: Mapping[str, str]
    analyzer_suffixes: frozenset[str]
    lockfile: str
    build_fingerprint: str

    def source_paths(self, inspection: ProjectInspection) -> tuple[PurePosixPath, ...]:
        return tuple(
            item.path
            for item in inspection.editor_documents
            if item.path.suffix.lower() in self.analyzer_suffixes
        )

    def analyze(
        self,
        project: ViewProject,
        inspection: ProjectInspection,
        execution: _deno.DenoExecution,
    ) -> SourceAnalysis:
        lockfile = validate_relative_path(
            project.options.get("lockfile", self.lockfile),
            field=f"{self.provider_id} lockfile",
        )
        return analyze_sources(
            project,
            self.provider_id,
            self.analyzer_package,
            self.source_paths(inspection),
            lockfile,
            execution,
        )

    def inspect(
        self,
        request: InspectionRequest,
        availability: ProviderAvailability,
        *,
        preflight_diagnostics: tuple[ProjectDiagnostic, ...] = (),
    ) -> ProjectInspection:
        project = request.project
        configured_paths: dict[str, PurePosixPath] = {}
        option_diagnostics = [
            ProjectDiagnostic(
                code="provider-options-invalid",
                severity="error",
                message=f"{self.provider_id} received undeclared option {name!r}",
                hint="Edit view.toml to use supported provider options.",
                source=SourceLocation(PurePosixPath("view.toml"), 1, 1),
            )
            for name in sorted(set(project.options) - set(self.option_paths))
        ]
        for name, default in self.option_paths.items():
            try:
                configured_paths[name] = validate_relative_path(
                    project.options.get(name, default),
                    field=f"{self.provider_id} {name}",
                )
            except ValueError as error:
                option_diagnostics.append(
                    ProjectDiagnostic(
                        code="provider-options-invalid",
                        severity="error",
                        message=str(error),
                        hint="Edit view.toml to use supported provider options.",
                        source=SourceLocation(PurePosixPath("view.toml"), 1, 1),
                    )
                )
        entrypoint = configured_paths.get("entrypoint")
        entrypoint_roots = (
            (entrypoint.parent.as_posix(),)
            if entrypoint is not None and entrypoint.parent != PurePosixPath(".")
            else ()
        )
        inventory_roots = tuple(
            dict.fromkeys(
                (
                    *(item.path.as_posix() for item in self.input_scope),
                    *(path.as_posix() for path in self.document_roots),
                    *(path.as_posix() for path in configured_paths.values()),
                    *entrypoint_roots,
                )
            )
        )
        read_only = set(self.read_only)
        if lockfile := configured_paths.get("lockfile"):
            read_only.add(lockfile.as_posix())
        editor_documents = _deno.project_inventory(
            project,
            inventory_roots,
            self.editor_languages,
            read_only=frozenset(read_only),
        )
        diagnostics = list(preflight_diagnostics)
        diagnostic_keys = {
            (item.code, item.severity, item.message) for item in diagnostics
        }
        for item in option_diagnostics:
            key = (item.code, item.severity, item.message)
            if key not in diagnostic_keys:
                diagnostics.append(item)
                diagnostic_keys.add(key)
        diagnostics.extend(
            ProjectDiagnostic(
                code="project-input-missing",
                severity="error",
                message=f"{self.provider_id} requires {relative}.",
            )
            for relative in (
                *self.required_files,
                *(path.as_posix() for path in configured_paths.values()),
            )
            if not (project.root / relative).is_file()
        )
        sites = ()
        inspection = ProjectInspection(
            editor_documents=editor_documents,
            input_scope=self.input_scope,
            mounts=(),
            diagnostics=(),
            build_fingerprint=self.build_fingerprint,
        )
        if availability.available and not diagnostics:
            try:
                analysis = self.analyze(
                    project,
                    inspection,
                    _deno.create_execution(
                        project,
                        cache_root=request.cache_root,
                        cancellation=request.cancellation,
                        runner=request.runner,
                    ),
                )
            except ValueError as error:
                diagnostics.append(
                    ProjectDiagnostic(
                        code="provider-options-invalid",
                        severity="error",
                        message=str(error),
                    )
                )
            else:
                sites = analysis.sites
                diagnostics.extend(analysis.diagnostics)
        elif not availability.available:
            diagnostics.append(
                ProjectDiagnostic(
                    code="provider-unavailable",
                    severity="error",
                    message=availability.reason or "Deno is unavailable.",
                    hint=availability.action or "",
                )
            )
        input_scope = list(self.input_scope)
        for name, path in configured_paths.items():
            candidate = (
                path.parent
                if name == "entrypoint" and path.parent != PurePosixPath(".")
                else path
            )
            kind = "directory" if candidate != path else "file"
            if any(
                item.path == candidate
                or (
                    item.kind == "directory"
                    and (
                        item.path == PurePosixPath(".")
                        or item.path in candidate.parents
                    )
                )
                for item in input_scope
            ):
                continue
            input_scope.append(ProjectInput(candidate, kind))
        return ProjectInspection(
            editor_documents=editor_documents,
            input_scope=tuple(input_scope),
            mounts=sites,
            diagnostics=tuple(diagnostics),
            build_fingerprint=self.build_fingerprint,
        )


def copy_public_assets(
    work: Path,
    output: Path,
    public: PurePosixPath = _DEFAULT_PUBLIC_ROOT,
    cancellation: ProviderCancellation | None = None,
) -> None:
    """Merge staged public files into provider output without collisions."""
    _copy_public_assets(work, output, public, cancellation)


def _copy_public_assets(
    work: Path,
    output: Path,
    public: PurePosixPath,
    cancellation: ProviderCancellation | None,
) -> None:
    source = work.joinpath(*public.parts)
    if not source.exists():
        return
    if source.is_symlink() or not source.is_dir():
        raise ValueError(f"Public asset root must be a directory: {public}")
    cancelled = (lambda: cancellation.cancelled) if cancellation is not None else None
    combined_limit = min(
        ARTIFACT_OUTPUT_BUDGET.max_files,
        PROJECT_INPUT_BUDGET.max_files,
    )
    seen_files: set[Path] = set()
    seen_entries: set[Path] = set()
    try:
        output_files = bounded_regular_files(
            output,
            max_files=combined_limit,
            label="Provider output",
            seen=seen_files,
            seen_entries=seen_entries,
            cancelled=cancelled,
        )
        source_files = bounded_regular_files(
            source,
            max_files=combined_limit,
            label="Public assets",
            seen=seen_files,
            seen_entries=seen_entries,
            cancelled=cancelled,
        )
    except ConfigurationError as error:
        raise ValueError(str(error)) from error
    occupied: dict[str, PurePosixPath] = {}
    budget = FileBudgetTracker(ARTIFACT_OUTPUT_BUDGET, "Provider output")

    def add_to_budget(relative: PurePosixPath, path: Path) -> None:
        try:
            budget.add(relative.as_posix(), path.stat().st_size)
        except ConfigurationError as error:
            raise ValueError(str(error)) from error

    for path in sorted(output_files):
        relative = PurePosixPath(path.relative_to(output).as_posix())
        occupied[relative.as_posix().casefold()] = relative
        add_to_budget(relative, path)

    assets: dict[str, tuple[PurePosixPath, Path]] = {}
    for path in sorted(source_files):
        relative = validate_relative_path(
            path.relative_to(source).as_posix(),
            field="Public asset",
        )
        key = relative.as_posix().casefold()
        previous = assets.get(key)
        if previous is not None:
            raise ValueError(
                f"Public assets collide by case: {previous[0]} and {relative}"
            )
        assets[key] = (relative, path)

    for key, (relative, source_path) in assets.items():
        if cancellation is not None and cancellation.cancelled:
            raise ProviderCommandError("Deno public asset staging was cancelled")
        conflict = occupied.get(key)
        if conflict is None:
            for occupied_key, occupied_path in occupied.items():
                if key.startswith(f"{occupied_key}/") or occupied_key.startswith(
                    f"{key}/"
                ):
                    conflict = occupied_path
                    break
        if conflict is not None:
            raise ValueError(
                f"Public asset {relative} collides with generated output {conflict}"
            )
        add_to_budget(relative, source_path)
        target = output.joinpath(*relative.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target)
        occupied[key] = relative


def failure(
    provider: str,
    code: str,
    operation: str,
    output: str,
) -> ProjectDiagnostic:
    """Return one actionable provider command diagnostic."""
    return ProjectDiagnostic(
        code=code,
        severity="error",
        message=f"{provider} could not {operation}: {output.strip()}",
        hint="Fix the reported source or dependency error and build the view again.",
    )


def command(
    provider: str,
    project: ViewProject,
    arguments: tuple[str, ...] | list[str],
    *,
    cwd: Path,
    code: str,
    operation: str,
    execution: _deno.DenoExecution,
    environment: Mapping[str, str] | None = None,
    network_environment: bool = False,
) -> tuple[ProviderCommandResult | None, ProjectDiagnostic | None]:
    """Run one provider command and convert supervisor failures."""
    try:
        return (
            execution.run(
                arguments,
                cwd=cwd,
                environment=environment,
                network_environment=network_environment,
            ),
            None,
        )
    except _deno.DenoExecutionError as error:
        return None, failure(provider, code, operation, str(error))
