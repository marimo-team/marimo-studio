"""Validate provider requests and results before Studio trusts them.

The conformance boundary checks record types, browser-safe data,
portable contained paths, and explicit size and count limits. It also checks
Source documents and build inputs separately, and rejects path collisions or
overlapping declarations before they enter workspace or artifact state.

Studio reserves ``view.toml`` and generated control paths. Installed providers
can describe and build their frontend format while Studio retains ownership of
workspace mutation, publication, sessions, and browser policy.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import math
from collections.abc import Collection, Mapping
from dataclasses import replace
from pathlib import Path, PurePosixPath
from typing import TypeVar, cast

from marimo_studio._filesystem.budgets import BUILD_INPUT_BUDGET
from marimo_studio.view_providers import (
    BuildInput,
    BuildProfile,
    BuildRequest,
    BuildResult,
    DocumentProvider,
    InspectionRequest,
    JsonValue,
    ProjectDiagnostic,
    ProjectInspection,
    ProviderAvailability,
    ProviderCancellation,
    ProviderError,
    ProviderInfo,
    RenderCell,
    RenderOutput,
    RenderRequest,
    RenderValue,
    Representation,
    Size,
    SourceDocument,
    SourceLocation,
    ViewProject,
    ViewProvider,
    project_path,
)
from marimo_studio.view_providers._host._shapes import (
    MANIFEST_PATH,
    MAX_DOCUMENTS,
    checked_json,
    checked_text,
    checked_tuple,
    conformance_error,
    contains,
    core_path,
    input_path,
    is_manifest,
    overlaps,
    provider_path,
    require_casefold_unique,
    require_disjoint_paths,
    require_unique,
)
from marimo_studio.view_providers._host.records import ProviderProvenance
from marimo_studio.view_providers._records import DOCUMENT_MEDIA_TYPES
from marimo_studio.view_providers._targets import (
    MAX_CELL_TARGETS,
    MAX_VALUE_TARGETS,
    validate_projection_target,
)
from marimo_studio.view_providers._validation import (
    InvalidTargetError,
    accept_diagnostics,
    validate_project_diagnostic,
    validate_projection_site,
    validate_render_value,
)

_PROFILES = frozenset({"development", "production"})
_BUILD_CONTRACT_VERSION = 3
_GUIDANCE_DOCUMENTS = (PurePosixPath("AGENTS.md"), PurePosixPath("DESIGN.md"))
_MAX_OPTIONS = 256
_MAX_BUILD_INPUTS = BUILD_INPUT_BUDGET.max_files
_MAX_SITES = 512
_Read = TypeVar("_Read", RenderValue, RenderOutput, RenderCell)
_MAX_SITE_BYTES = 1024 * 1024
_MAX_DIAGNOSTICS = 512
_MAX_DIAGNOSTIC_BYTES = 1024 * 1024
_UNAVAILABLE_REASON = "The provider reported that it is unavailable."
_UNAVAILABLE_ACTION = "Repair the provider installation or choose another provider."


def provider_methods(provider: object) -> bool:
    """Check a provider's synchronous methods and return whether it renders."""
    for method in ("availability", "starters", "create", "inspect", "build"):
        operation = getattr(provider, method, None)
        if not callable(operation):
            raise ValueError(f"provider requires {method}()")
        if inspect.iscoroutinefunction(operation):
            raise ValueError(f"provider {method}() must be synchronous")
    render = getattr(provider, "render", None)
    if inspect.iscoroutinefunction(render):
        raise ValueError("provider render() must be synchronous")
    return callable(render)


# Source opens a raised error's file so the author can repair it there. Editor
# language IDs that Source highlights, by suffix. Other files open as text.
_SOURCE_LANGUAGES = {
    ".css": "css",
    ".html": "html",
    ".js": "javascript",
    ".jsx": "javascriptreact",
    ".ts": "typescript",
    ".tsx": "typescriptreact",
}


def _located(
    diagnostic: ProjectDiagnostic,
    documents: Collection[PurePosixPath],
) -> ProjectDiagnostic:
    """Move a source outside ``documents`` into the diagnostic's message."""
    source = diagnostic.source
    if source is None or source.path in documents:
        return diagnostic
    return replace(
        diagnostic,
        message=(
            f"{source.path.as_posix()}:{source.line}:{source.column}: "
            f"{diagnostic.message}"
        ),
        source=None,
    )


def _failed_inspection(root: Path, diagnostic: ProjectDiagnostic) -> ProjectInspection:
    """Describe a project whose ``inspect()`` raised ``diagnostic``."""
    source = diagnostic.source
    if source is None or source.path == MANIFEST_PATH:
        return ProjectInspection((), (), diagnostics=(diagnostic,))
    try:
        project_path(source.path, field="Diagnostic source")
    except ValueError:
        # Validation reports the unsafe path. Keep it off the filesystem.
        return ProjectInspection((), (), diagnostics=(diagnostic,))
    file = root.joinpath(*source.path.parts)
    if file.is_symlink() or not file.is_file():
        return ProjectInspection((), (), diagnostics=(_located(diagnostic, ()),))
    document = SourceDocument(
        source.path,
        _SOURCE_LANGUAGES.get(source.path.suffix.lower(), "text"),
        "edit",
    )
    return ProjectInspection((document,), (), diagnostics=(diagnostic,))


class ProviderConformance:
    """Normalize one installed provider at the extension boundary."""

    def __init__(
        self,
        key: str,
        info: object,
        *,
        distribution: str,
        version: str,
    ) -> None:
        self.key = key
        self.info = self.validate_info(info, provider=key)
        self.distribution = distribution
        self.version = version

    @staticmethod
    def validate_info(value: object, *, provider: str = "unknown") -> ProviderInfo:
        """Return compact provider information after structural validation."""
        if not isinstance(value, ProviderInfo):
            raise conformance_error(
                provider, "requires info to be a ProviderInfo record"
            )
        checked_text(value.title, provider, "title")
        checked_text(value.summary, provider, "summary")
        if not isinstance(value.options, frozenset) or not all(
            isinstance(name, str) and name for name in value.options
        ):
            raise conformance_error(
                provider, "requires options to be a frozenset of names"
            )
        return value

    def validate_availability(self, value: object) -> ProviderAvailability:
        if (
            not isinstance(value, ProviderAvailability)
            or type(value.available) is not bool
        ):
            raise conformance_error(self.key, "returned an invalid availability record")
        for field, item in (
            ("availability version", value.version),
            ("availability reason", value.reason),
            ("availability action", value.action),
        ):
            if item is not None:
                checked_text(item, self.key, field)
        if not value.available:
            return replace(
                value,
                reason=value.reason or _UNAVAILABLE_REASON,
                action=value.action or _UNAVAILABLE_ACTION,
            )
        return value

    def validate_project(self, value: object) -> ViewProject:
        if not isinstance(value, ViewProject):
            raise conformance_error(self.key, "requires a ViewProject record")
        if value.provider != self.key:
            raise conformance_error(
                self.key, f"cannot inspect project for {value.provider!r}"
            )
        return replace(value, options=self.validate_options(value.options))

    def validate_options(self, value: object) -> Mapping[str, JsonValue]:
        if not isinstance(value, Mapping):
            raise conformance_error(self.key, "requires options to be a mapping")
        if len(value) > _MAX_OPTIONS:
            raise conformance_error(
                self.key, f"limits options to {_MAX_OPTIONS} entries"
            )
        if any(not isinstance(name, str) for name in value):
            raise conformance_error(self.key, "requires option names to be strings")
        normalized = checked_json(
            dict(cast(Mapping[str, object], value)),
            self.key,
            "options",
        )
        return cast(dict[str, JsonValue], normalized)

    def validate_inspection(
        self,
        project: object,
        value: object,
    ) -> ProjectInspection:
        root = self.validate_project(project).root
        if not isinstance(value, ProjectInspection):
            raise conformance_error(self.key, "requires a ProjectInspection record")
        documents = checked_tuple(
            value.documents,
            self.key,
            "Source documents",
            maximum=MAX_DOCUMENTS,
        )
        accepted: list[SourceDocument] = []
        document_paths: list[PurePosixPath] = []
        for item in documents:
            if not isinstance(item, SourceDocument):
                raise conformance_error(self.key, "requires SourceDocument records")
            accepted.append(item)
            path = provider_path(item.path, self.key, "Source document path")
            if is_manifest(path):
                raise conformance_error(
                    self.key,
                    "cannot expose Studio-owned 'view.toml' in the editor",
                )
            document_paths.append(path)
            checked_text(item.language, self.key, "Source document language")
            if item.access not in {"edit", "read"}:
                raise conformance_error(
                    self.key, "returned invalid Source document access"
                )
            if item.label is not None:
                checked_text(item.label, self.key, "Source document label")
        guidance = tuple(
            SourceDocument(path, "markdown", "edit")
            for path in _GUIDANCE_DOCUMENTS
            if path not in document_paths
            and not root.joinpath(path).is_symlink()
            and root.joinpath(path).is_file()
        )
        document_paths.extend(item.path for item in guidance)
        require_unique(tuple(document_paths), self.key, "Source document paths")
        require_casefold_unique(
            tuple(document_paths),
            self.key,
            "Source document paths",
        )
        scope: list[BuildInput] = []
        for item in checked_tuple(
            value.inputs,
            self.key,
            "build inputs",
            maximum=_MAX_BUILD_INPUTS,
        ):
            if not isinstance(item, BuildInput) or item.kind not in {
                "file",
                "directory",
            }:
                raise conformance_error(self.key, "requires BuildInput records")
            scope.append(
                BuildInput(
                    input_path(item.path, self.key, item.kind),
                    item.kind,
                )
            )
        normalized_scope = tuple(scope)
        require_disjoint_paths(
            (item.path for item in normalized_scope), self.key, "build input"
        )

        def covered(path: PurePosixPath) -> bool:
            return any(
                item.path == path if item.kind == "file" else contains(item.path, path)
                for item in scope
            )

        def require_input(path: PurePosixPath, declaration: str) -> None:
            if is_manifest(path) or not covered(path):
                raise conformance_error(
                    self.key,
                    f"declares {declaration} in {path.as_posix()!r} "
                    "outside its build inputs",
                )

        manifest = MANIFEST_PATH
        if not covered(manifest):
            scope.append(BuildInput(manifest, "file"))
            # A declared `VIEW.TOML` misses the exact match above and would
            # collide by case with the manifest Studio adds.
            require_disjoint_paths(
                (item.path for item in scope), self.key, "build input"
            )
        document_set = set(document_paths)
        diagnostic_sources = {*document_set, manifest}
        self._diagnostics(value.diagnostics, "diagnostics", diagnostic_sources)
        sites = []
        site_bytes = 0
        for site in checked_tuple(
            value.sites,
            self.key,
            "projection sites",
            maximum=_MAX_SITES,
        ):
            try:
                validated_site = validate_projection_site(
                    site,
                    documents=document_set,
                )
            except ValueError as error:
                raise conformance_error(self.key, str(error)) from error
            require_input(validated_site.source.path, "a projection site")
            site_bytes += len(
                json.dumps(
                    validated_site.to_dict(),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
            )
            if site_bytes > _MAX_SITE_BYTES:
                raise conformance_error(
                    self.key,
                    f"limits projection sites to {_MAX_SITE_BYTES} encoded bytes",
                )
            sites.append(validated_site)
        require_unique(
            tuple((site.source.path, site.offset) for site in sites),
            self.key,
            "projection site offsets",
        )
        invalid_reads: list[ProjectDiagnostic] = []

        def reads(items: object, record: type[_Read], kind: str) -> tuple[_Read, ...]:
            label = f"render {kind}s"
            validated: list[_Read] = []
            for item in checked_tuple(items, self.key, label, maximum=_MAX_SITES):
                if not isinstance(item, record):
                    raise conformance_error(
                        self.key, f"requires {label} to be {record.__name__} records"
                    )
                try:
                    validate_render_value(item, documents=document_set)
                except InvalidTargetError as error:
                    invalid_reads.append(
                        ProjectDiagnostic(
                            f"render-{kind}-invalid",
                            "error",
                            str(error),
                            (
                                'Read a cell by its name, such as "summary".'
                                if kind == "cell"
                                else f'Read a {kind} such as "summary" or '
                                '"summary.total".'
                            ),
                            error.source,
                        )
                    )
                    continue
                except ValueError as error:
                    raise conformance_error(self.key, str(error)) from error
                require_input(item.source.path, f"a render {kind}")
                validated.append(item)
            limit = MAX_CELL_TARGETS if kind == "cell" else MAX_VALUE_TARGETS
            if len({item.target for item in validated}) > limit:
                raise conformance_error(
                    self.key,
                    f"limits {label} to {limit} unique targets",
                )
            return tuple(validated)

        render_values = reads(value.render_values, RenderValue, "value")
        render_outputs = reads(value.render_outputs, RenderOutput, "output")
        render_cells = reads(value.render_cells, RenderCell, "cell")
        return replace(
            value,
            documents=(*accepted, *guidance),
            inputs=tuple(scope),
            render_values=render_values,
            render_outputs=render_outputs,
            render_cells=render_cells,
            diagnostics=(
                *value.diagnostics,
                *invalid_reads,
                *accept_diagnostics(sites, (*render_outputs, *render_cells)),
            ),
        )

    def _operation_owners(
        self,
        value: InspectionRequest | BuildRequest | RenderRequest,
        operation: str,
    ) -> None:
        if not isinstance(value.cancellation, ProviderCancellation):
            raise conformance_error(self.key, "requires a ProviderCancellation owner")
        if not callable(getattr(value.runner, "run", None)):
            raise conformance_error(self.key, "requires a supervised provider runner")
        if (
            not isinstance(value.command_timeout, (int, float))
            or isinstance(value.command_timeout, bool)
            or not math.isfinite(value.command_timeout)
            or value.command_timeout <= 0
        ):
            raise conformance_error(
                self.key,
                f"requires a positive finite {operation} command budget",
            )

    def _diagnostics(
        self,
        value: object,
        label: str,
        documents: set[PurePosixPath] | None,
    ) -> tuple[ProjectDiagnostic, ...]:
        diagnostics: list[ProjectDiagnostic] = []
        encoded = 0
        for item in checked_tuple(value, self.key, label, maximum=_MAX_DIAGNOSTICS):
            try:
                diagnostic = validate_project_diagnostic(item, documents=documents)
            except ValueError as error:
                raise conformance_error(self.key, str(error)) from error
            encoded += len(
                (
                    diagnostic.code
                    + diagnostic.message
                    + diagnostic.hint
                    + (diagnostic.source.path.as_posix() if diagnostic.source else "")
                ).encode("utf-8")
            )
            if encoded > _MAX_DIAGNOSTIC_BYTES:
                raise conformance_error(
                    self.key,
                    f"limits {label} to {_MAX_DIAGNOSTIC_BYTES} encoded bytes",
                )
            diagnostics.append(diagnostic)
        return tuple(diagnostics)

    def inspect(
        self,
        provider: ViewProvider,
        request: InspectionRequest,
    ) -> ProjectInspection:
        """Inspect with ``provider`` and validate the result.

        Undeclared ``view.toml`` options and a raised ``ProviderError`` become
        inspection diagnostics.
        """
        unknown = sorted(set(request.project.options) - self.info.options)
        if unknown:
            supported = ", ".join(sorted(self.info.options)) or "none"
            inspection = ProjectInspection(
                (),
                (),
                diagnostics=(
                    ProjectDiagnostic(
                        "provider-options-invalid",
                        "error",
                        f"view.toml sets {unknown[0]!r}, which "
                        f"{self.info.title} does not read.",
                        f"Remove it from view.toml. Supported options: {supported}.",
                        SourceLocation(MANIFEST_PATH, 1, 1),
                    ),
                ),
            )
        else:
            try:
                inspection = provider.inspect(request)
            except ProviderError as error:
                inspection = _failed_inspection(request.project.root, error.diagnostic)
        return self.validate_inspection(request.project, inspection)

    def build(self, provider: ViewProvider, request: BuildRequest) -> BuildResult:
        """Build with ``provider``. A raised ``ProviderError`` fails the build."""
        try:
            result = provider.build(request)
        except ProviderError as error:
            documents = {
                MANIFEST_PATH,
                *(item.path for item in request.inspection.documents),
            }
            result = BuildResult(None, (_located(error.diagnostic, documents),))
        return self.validate_build_result(request, result)

    def render(self, provider: DocumentProvider, request: RenderRequest) -> BuildResult:
        """Render with ``provider``. A raised ``ProviderError`` fails the render."""
        try:
            result = provider.render(request)
        except ProviderError as error:
            result = BuildResult(None, (error.diagnostic,))
        return self.validate_render_result(request, result)

    def validate_inspection_request(self, value: object) -> InspectionRequest:
        if not isinstance(value, InspectionRequest):
            raise conformance_error(self.key, "requires an InspectionRequest record")
        project = self.validate_project(value.project)
        cache = core_path(value.cache_root, self.key, "inspection cache root")
        if overlaps(cache, project.root):
            raise conformance_error(
                self.key,
                "requires inspection cache outside the view project",
            )
        if cache.exists() and not cache.is_dir():
            raise conformance_error(
                self.key, "requires inspection cache root to be a directory"
            )
        self._operation_owners(value, "inspection")
        return replace(value, project=project, cache_root=cache)

    def validate_build_request(self, value: object) -> BuildRequest:
        if not isinstance(value, BuildRequest):
            raise conformance_error(self.key, "requires a BuildRequest record")
        project = self.validate_project(value.project)
        inspection = self.validate_inspection(project, value.inspection)
        self.validate_profile(value.profile)
        inputs = tuple(
            provider_path(item, self.key, "build input path")
            for item in checked_tuple(
                value.inputs,
                self.key,
                "build inputs",
                maximum=_MAX_BUILD_INPUTS,
            )
        )
        require_unique(inputs, self.key, "build input paths")
        if not inputs:
            raise conformance_error(self.key, "requires enumerated build inputs")
        snapshot = core_path(project.root, self.key, "snapshot root")
        staging = core_path(value.staging_root, self.key, "staging root")
        cache = core_path(value.cache_root, self.key, "cache root")
        work = core_path(value.work_root, self.key, "work root")
        if not staging.is_dir() or not work.is_dir():
            raise conformance_error(
                self.key, "requires existing staging and work directories"
            )
        if overlaps(work, staging):
            raise conformance_error(self.key, "requires a work root outside staging")
        if cache.name != ".cache" or cache.parent.name != ".artifacts":
            raise conformance_error(
                self.key, "requires cache root to end with .artifacts/.cache"
            )
        if cache.exists() and not cache.is_dir():
            raise conformance_error(self.key, "requires cache root to be a directory")
        if overlaps(cache, snapshot) or overlaps(cache, staging):
            raise conformance_error(
                self.key, "requires cache outside snapshot and staging roots"
            )
        self._operation_owners(value, "build")
        checked_text(value.project_revision, self.key, "project revision")
        return replace(
            value,
            project=project,
            inspection=inspection,
            inputs=inputs,
            work_root=work,
        )

    def validate_build_result(
        self,
        request: BuildRequest,
        value: object,
    ) -> BuildResult:
        if not isinstance(value, BuildResult):
            raise conformance_error(self.key, "requires a BuildResult record")
        documents = {
            *(item.path for item in request.inspection.documents),
            MANIFEST_PATH,
        }
        normalized_diagnostics = self._diagnostics(
            value.diagnostics,
            "build diagnostics",
            documents,
        )
        outputs = {item.target for item in request.inspection.render_outputs}
        if not isinstance(value.output_sizes, Mapping):
            raise conformance_error(self.key, "requires output_sizes as a mapping")
        for target, size in value.output_sizes.items():
            if target not in outputs or not isinstance(size, Size):
                raise conformance_error(
                    self.key,
                    f"measured {target!r}, which is not an output the document "
                    "reads, or gave it no Size",
                )
        if value.document is None:
            if not any(item.severity == "error" for item in normalized_diagnostics):
                raise conformance_error(
                    self.key, "returned no document or error diagnostic"
                )
            return replace(value, diagnostics=normalized_diagnostics)
        document = provider_path(value.document, self.key, "build document")
        if not request.staging_root.joinpath(*document.parts).is_file():
            raise conformance_error(
                self.key,
                f"returned missing build document {document.as_posix()!r}",
            )
        return replace(value, document=document, diagnostics=normalized_diagnostics)

    def validate_render_request(self, value: object) -> RenderRequest:
        if not isinstance(value, RenderRequest):
            raise conformance_error(self.key, "requires a RenderRequest record")
        template = core_path(value.template_root, self.key, "render template root")
        output = core_path(value.output_root, self.key, "render output root")
        if not template.is_dir() or not output.is_dir() or any(output.iterdir()):
            raise conformance_error(
                self.key,
                "requires a template directory and an empty output directory",
            )
        if overlaps(template, output):
            raise conformance_error(
                self.key, "requires separate template and output roots"
            )
        document = provider_path(value.document, self.key, "render document")
        if not template.joinpath(*document.parts).is_file():
            raise conformance_error(
                self.key, f"has no render document {document.as_posix()!r}"
            )
        if not isinstance(value.values, Mapping):
            raise conformance_error(self.key, "requires render values to be a mapping")
        for target in value.values:
            try:
                validate_projection_target("value", target)
            except ValueError as error:
                raise conformance_error(
                    self.key,
                    f"received an invalid render target: {error}",
                ) from error
        for kind, media in (("output", value.outputs), ("cell", value.cells)):
            if not isinstance(media, Mapping):
                raise conformance_error(
                    self.key, f"requires render {kind}s to be a mapping"
                )
            for target, representation in media.items():
                try:
                    validate_projection_target(kind, target)
                except ValueError as error:
                    raise conformance_error(
                        self.key,
                        f"received an invalid render target: {error}",
                    ) from error
                if not isinstance(representation, Representation):
                    raise conformance_error(
                        self.key,
                        f"requires a Representation for render {kind} {target!r}",
                    )
        self._operation_owners(value, "render")
        return replace(value, template_root=template, output_root=output)

    def validate_render_result(
        self,
        request: RenderRequest,
        value: object,
    ) -> BuildResult:
        if not isinstance(value, BuildResult):
            raise conformance_error(self.key, "requires a BuildResult record")
        diagnostics = self._diagnostics(value.diagnostics, "render diagnostics", None)
        if value.document is None:
            if not any(item.severity == "error" for item in diagnostics):
                raise conformance_error(
                    self.key, "rendered no document or error diagnostic"
                )
            return replace(value, diagnostics=diagnostics)
        document = provider_path(value.document, self.key, "rendered document")
        if document.suffix.lower() not in DOCUMENT_MEDIA_TYPES:
            raise conformance_error(
                self.key,
                f"rendered {document.as_posix()!r}. Studio displays "
                f"{', '.join(sorted(DOCUMENT_MEDIA_TYPES))} documents",
            )
        output = request.output_root.joinpath(*document.parts)
        if (
            not output.is_file()
            or output.resolve()
            != request.output_root.resolve().joinpath(*document.parts)
        ):
            raise conformance_error(
                self.key, f"rendered no file at {document.as_posix()!r}"
            )
        return replace(value, document=document, diagnostics=diagnostics)

    def validate_profile(self, value: object) -> BuildProfile:
        if not isinstance(value, str) or value not in _PROFILES:
            raise conformance_error(
                self.key, f"does not support build profile {value!r}"
            )
        return cast(BuildProfile, value)

    def provenance(self, tool_version: str | None) -> ProviderProvenance:
        """Return compact provenance for builds with this provider and tool."""
        payload = json.dumps(
            [
                self.distribution,
                self.version,
                self.key,
                _BUILD_CONTRACT_VERSION,
                tool_version,
            ],
            separators=(",", ":"),
        ).encode()
        return ProviderProvenance(
            key=self.key,
            distribution=self.distribution,
            version=self.version,
            build_fingerprint=f"sha256:{hashlib.sha256(payload).hexdigest()}",
        )
