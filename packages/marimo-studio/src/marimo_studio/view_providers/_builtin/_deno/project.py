"""Compose provider project inspection, templates, and command diagnostics."""

from __future__ import annotations

import os
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from marimo_studio.view_providers import (
    BuildInput,
    InspectionRequest,
    ProjectDiagnostic,
    ProjectInspection,
    ProviderAvailability,
    ProviderCancellation,
    ProviderCommandResult,
    ProviderError,
    SourceDocument,
    ViewProject,
    project_files,
    project_path,
)
from marimo_studio.view_providers._builtin import _deno
from marimo_studio.view_providers._builtin._deno.analysis import (
    SourceAnalysis,
    analyze_sources,
)

_DEFAULT_PUBLIC_ROOT = PurePosixPath("public")


@dataclass(frozen=True)
class ProviderProjectSpec:
    """Define one provider's durable file and analyzer contract."""

    analyzer_package: str
    inputs: tuple[BuildInput, ...]
    required_files: tuple[str, ...]
    editor_languages: Mapping[str, str]
    read_only: frozenset[str]
    option_paths: Mapping[str, str]
    analyzer_suffixes: frozenset[str]

    @property
    def options(self) -> frozenset[str]:
        return frozenset(self.option_paths)

    def option_path(self, project: ViewProject, name: str) -> PurePosixPath:
        """Resolve a declared path option against this provider's defaults."""
        return project.path_option(name, default=self.option_paths[name])

    def source_paths(self, inspection: ProjectInspection) -> tuple[PurePosixPath, ...]:
        return tuple(
            item.path
            for item in inspection.documents
            if item.path.suffix.lower() in self.analyzer_suffixes
        )

    def analyze(
        self,
        project: ViewProject,
        inspection: ProjectInspection,
        execution: _deno.DenoExecution,
    ) -> SourceAnalysis:
        lockfile = self.option_path(project, "lockfile")
        return analyze_sources(
            project,
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
        option_diagnostics: list[ProjectDiagnostic] = []
        for name in self.option_paths:
            try:
                configured_paths[name] = self.option_path(project, name)
            except ProviderError as error:
                option_diagnostics.append(error.diagnostic)
        entrypoint = configured_paths.get("entrypoint")
        entrypoint_roots = (
            (entrypoint.parent.as_posix(),)
            if entrypoint is not None and entrypoint.parent != PurePosixPath(".")
            else ()
        )
        inventory_roots = tuple(
            dict.fromkeys(
                (
                    *(item.path.as_posix() for item in self.inputs),
                    *(path.as_posix() for path in configured_paths.values()),
                    *entrypoint_roots,
                )
            )
        )
        read_only = set(self.read_only)
        if lockfile := configured_paths.get("lockfile"):
            read_only.add(lockfile.as_posix())
        documents = self._documents(
            project,
            inventory_roots,
            frozenset(read_only),
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
                code="build-input-missing",
                severity="error",
                message=f"{project.provider} requires {relative}.",
            )
            for relative in (
                *self.required_files,
                *(path.as_posix() for path in configured_paths.values()),
            )
            if not (project.root / relative).is_file()
        )
        sites = ()
        inspection = ProjectInspection(documents, self.inputs)
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
        inputs = list(self.inputs)
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
                for item in inputs
            ):
                continue
            inputs.append(BuildInput(candidate, kind))
        return ProjectInspection(
            documents,
            tuple(inputs),
            sites=sites,
            diagnostics=tuple(diagnostics),
        )

    def _documents(
        self,
        project: ViewProject,
        roots: tuple[str, ...],
        read_only: frozenset[str],
    ) -> tuple[SourceDocument, ...]:
        """Return the editable files beneath ``roots``, in root order.

        Source opens the first document, so the order of ``roots`` puts the
        authored source ahead of configuration files.
        """
        files = project_files(project, roots={root.split("/")[0] for root in roots})
        documents: list[SourceDocument] = []
        for root in roots:
            for path in files:
                relative = path.as_posix()
                if relative != root and not relative.startswith(f"{root}/"):
                    continue
                language = self.editor_languages.get(
                    path.name,
                    self.editor_languages.get(path.suffix.lower()),
                )
                if language is not None and all(
                    item.path != path for item in documents
                ):
                    access = "read" if relative in read_only else "edit"
                    documents.append(SourceDocument(path, language, access))
        return tuple(documents)


def _regular_files(root: Path) -> list[Path]:
    """List regular files below ``root``. Studio bounds the published output."""
    files: list[Path] = []
    for directory, names, filenames in os.walk(root):
        for name in (*names, *filenames):
            if Path(directory, name).is_symlink():
                raise ValueError(f"Public asset tree contains a symlink: {name}")
        files.extend(Path(directory, name) for name in filenames)
    return files


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
    output_files = _regular_files(output)
    source_files = _regular_files(source)
    occupied: dict[str, PurePosixPath] = {}

    for path in sorted(output_files):
        relative = PurePosixPath(path.relative_to(output).as_posix())
        occupied[relative.as_posix().casefold()] = relative

    assets: dict[str, tuple[PurePosixPath, Path]] = {}
    for path in sorted(source_files):
        relative = project_path(
            path.relative_to(source).as_posix(), field="Public asset"
        )
        key = relative.as_posix().casefold()
        previous = assets.get(key)
        if previous is not None:
            raise ValueError(
                f"Public assets collide by case: {previous[0]} and {relative}"
            )
        assets[key] = (relative, path)

    for key, (relative, source_path) in assets.items():
        if cancellation is not None:
            cancellation.raise_if_cancelled("Deno public asset staging")
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
        target = output.joinpath(*relative.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target)
        occupied[key] = relative


MISSING_DEPENDENCY_HINT = (
    "Fix the reported source error. Add a missing package as the view's "
    "AGENTS.md describes, then build the view again."
)


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
        hint=(
            _deno.DOWNLOAD_FAILURE_HINT
            if _deno.download_failed(output)
            else MISSING_DEPENDENCY_HINT
        ),
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
