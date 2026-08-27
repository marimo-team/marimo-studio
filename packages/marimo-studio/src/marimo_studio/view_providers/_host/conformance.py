"""Validate provider requests and results before Studio trusts them.

The conformance boundary checks record types, API versions, browser-safe data,
portable contained paths, and explicit size and count limits. It also keeps
documents shown in Source distinct from the broader build-input scope, requires
those documents to be covered by that scope, and rejects path collisions or
overlapping declarations before they enter workspace or artifact state.

Studio reserves ``view.toml`` and generated control paths. Installed providers
can describe and build their frontend format while Studio retains ownership of
workspace mutation, publication, sessions, and browser policy.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import replace
from itertools import pairwise
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import cast

from marimo_studio._filesystem.budgets import PROJECT_INPUT_BUDGET, FileBudgetTracker
from marimo_studio.errors import ConfigurationError
from marimo_studio.view_providers import (
    PROVIDER_API_VERSION,
    BuildProfile,
    BuildRequest,
    BuildResult,
    InspectionRequest,
    JsonValue,
    ProjectDiagnostic,
    ProjectInput,
    ProjectInspection,
    ProviderAvailability,
    ProviderCancellation,
    ProviderInfo,
    ProviderStarter,
    SourceDocument,
    ViewProject,
)
from marimo_studio.view_providers._host.records import ProviderProvenance
from marimo_studio.view_providers._validation import (
    validate_mount_declaration,
    validate_project_diagnostic,
    validate_relative_path,
)

_STARTER_KEY = re.compile(r"[a-z0-9](?:[a-z0-9._/-]*[a-z0-9])?")
_PROFILES = frozenset({"development", "production"})
_RESERVED_ROOTS = frozenset({".artifacts", ".gitignore", ".locks"})
_BUILD_CONTRACT_VERSION = 2
_MANIFEST_PATH = PurePosixPath("view.toml")
_MAX_TEXT_BYTES = 64 * 1024
_MAX_JSON_BYTES = 64 * 1024
_MAX_JSON_DEPTH = 32
_MAX_JSON_NODES = 4_096
_MAX_OPTIONS = 256
_MAX_STARTERS = 256
_MAX_DOCUMENTS = 256
_MAX_INPUT_SCOPE = PROJECT_INPUT_BUDGET.max_files
_MAX_MOUNTS = 512
_MAX_MOUNT_BYTES = 1024 * 1024
_MAX_DIAGNOSTICS = 512
_MAX_DIAGNOSTIC_BYTES = 1024 * 1024
_MAX_SAFE_INTEGER = (1 << 53) - 1


def _is_manifest(path: PurePosixPath) -> bool:
    return path.as_posix().casefold() == _MANIFEST_PATH.as_posix()


def _error(provider: str, message: str) -> ConfigurationError:
    return ConfigurationError(f"View provider {provider!r} {message}")


def _text(value: object, provider: str, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise _error(provider, f"requires {field} to be a non-empty string")
    if len(value.encode("utf-8")) > _MAX_TEXT_BYTES:
        raise _error(
            provider, f"requires {field} to fit within {_MAX_TEXT_BYTES} bytes"
        )
    return value


def _tuple(
    value: object,
    provider: str,
    field: str,
    *,
    maximum: int,
) -> tuple[object, ...]:
    if not isinstance(value, tuple):
        raise _error(provider, f"requires {field} to be a tuple")
    if len(value) > maximum:
        raise _error(provider, f"limits {field} to {maximum} records")
    return value


def _unique(values: tuple[object, ...], provider: str, field: str) -> None:
    if len(values) != len(set(values)):
        raise _error(provider, f"requires unique {field}")


def _json_value(value: object, provider: str, field: str) -> JsonValue:
    nodes = 0

    def normalize_json(item: object, depth: int) -> JsonValue:
        nonlocal nodes
        nodes += 1
        if nodes > _MAX_JSON_NODES:
            raise _error(provider, f"limits {field} to {_MAX_JSON_NODES} JSON values")
        if depth > _MAX_JSON_DEPTH:
            raise _error(provider, f"limits {field} to {_MAX_JSON_DEPTH} JSON levels")
        if item is None or type(item) is bool:
            return cast(JsonValue, item)
        if type(item) is int:
            if abs(cast(int, item)) > _MAX_SAFE_INTEGER:
                raise _error(provider, f"requires browser-safe integers in {field}")
            return cast(JsonValue, item)
        if type(item) is str:
            if len(item.encode("utf-8")) > _MAX_TEXT_BYTES:
                raise _error(provider, f"requires strings in {field} to be bounded")
            return cast(JsonValue, item)
        if type(item) is float:
            if not math.isfinite(cast(float, item)):
                raise _error(provider, f"requires finite numbers in {field}")
            return cast(JsonValue, item)
        if type(item) is list:
            return [
                normalize_json(child, depth + 1) for child in cast(list[object], item)
            ]
        if type(item) is dict and all(type(key) is str for key in item):
            return {
                key: normalize_json(child, depth + 1)
                for key, child in cast(dict[str, object], item).items()
            }
        raise _error(provider, f"requires JSON-compatible values in {field}")

    normalized = normalize_json(value, 0)
    encoded = json.dumps(
        normalized,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(encoded) > _MAX_JSON_BYTES:
        raise _error(provider, f"limits {field} to {_MAX_JSON_BYTES} encoded bytes")
    return normalized


def _provider_path(value: object, provider: str, field: str) -> PurePosixPath:
    if type(value) is not PurePosixPath:
        raise _error(provider, f"requires {field} to be a PurePosixPath")
    try:
        path = validate_relative_path(value, field=field)
    except ValueError as error:
        raise _error(provider, str(error)) from error
    if len(path.as_posix().encode("utf-8")) > _MAX_TEXT_BYTES:
        raise _error(
            provider, f"requires {field} to fit within {_MAX_TEXT_BYTES} bytes"
        )
    if path.parts[0].casefold() in {name.casefold() for name in _RESERVED_ROOTS}:
        raise _error(provider, f"reserves top-level {path.parts[0]!r} for Studio")
    return path


def _input_path(value: object, provider: str, kind: str) -> PurePosixPath:
    if (
        kind == "directory"
        and type(value) is PurePosixPath
        and value == PurePosixPath(".")
    ):
        return value
    return _provider_path(value, provider, "input scope path")


def _contains(root: PurePosixPath, path: PurePosixPath) -> bool:
    return root == PurePosixPath(".") or root == path or root in path.parents


def _path_shape(path: PurePosixPath) -> tuple[str, ...]:
    if path == PurePosixPath("."):
        return ()
    return tuple(part.casefold() for part in path.parts)


def _validate_casefold_unique_paths(
    paths: tuple[PurePosixPath, ...],
    provider: str,
    field: str,
) -> None:
    ordered = sorted((_path_shape(path), path.as_posix()) for path in paths)
    for (current_shape, current), (shape, path) in pairwise(ordered):
        if shape == current_shape:
            raise _error(
                provider,
                f"returned case-colliding {field} {current!r} and {path!r}",
            )


def _validate_non_overlapping_scope(
    scope: tuple[ProjectInput, ...],
    provider: str,
) -> None:
    ordered = sorted(
        (_path_shape(item.path), index, item) for index, item in enumerate(scope)
    )
    for (current_shape, _, current), (shape, _, item) in pairwise(ordered):
        shared = min(len(shape), len(current_shape))
        if shape[:shared] != current_shape[:shared]:
            continue
        relation = (
            "case-colliding" if len(shape) == len(current_shape) else "overlapping"
        )
        raise _error(
            provider,
            f"returned {relation} input scope paths "
            f"{current.path.as_posix()!r} and {item.path.as_posix()!r}",
        )


def _core_path(value: object, provider: str, field: str) -> Path:
    if not isinstance(value, Path) or not value.is_absolute():
        raise _error(provider, f"requires {field} to be an absolute path")
    return value


def _overlap(first: Path, second: Path) -> bool:
    return first == second or first in second.parents or second in first.parents


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
            raise _error(provider, "requires info to be a ProviderInfo record")
        if (
            type(value.api_version) is not int
            or value.api_version != PROVIDER_API_VERSION
        ):
            raise _error(
                provider,
                f"uses API version {value.api_version!r}. "
                f"Studio requires {PROVIDER_API_VERSION}",
            )
        _text(value.title, provider, "title")
        _text(value.summary, provider, "summary")
        return value

    def validate_availability(self, value: object) -> ProviderAvailability:
        if (
            not isinstance(value, ProviderAvailability)
            or type(value.available) is not bool
        ):
            raise _error(self.key, "returned an invalid availability record")
        for field, item in (
            ("availability version", value.version),
            ("availability reason", value.reason),
            ("availability action", value.action),
        ):
            if item is not None:
                _text(item, self.key, field)
        return value

    def validate_starters(self, value: object) -> tuple[ProviderStarter, ...]:
        records = _tuple(
            value,
            self.key,
            "starters",
            maximum=_MAX_STARTERS,
        )
        starters: list[ProviderStarter] = []
        keys: list[str] = []
        for item in records:
            if not isinstance(item, ProviderStarter):
                raise _error(self.key, "requires ProviderStarter records")
            key = _text(item.key, self.key, "starter key")
            if _STARTER_KEY.fullmatch(key) is None:
                raise _error(self.key, f"declares invalid starter key {key!r}")
            _text(item.title, self.key, "starter title")
            _text(item.summary, self.key, "starter summary")
            documents = tuple(
                _provider_path(path, self.key, "starter document")
                for path in _tuple(
                    item.documents,
                    self.key,
                    "starter documents",
                    maximum=_MAX_DOCUMENTS,
                )
            )
            if any(_is_manifest(path) for path in documents):
                raise _error(self.key, "reserves top-level 'view.toml' for Studio")
            if not documents:
                raise _error(self.key, f"starter {key!r} requires a document")
            _unique(documents, self.key, "starter documents")
            keys.append(key)
            starters.append(item)
        _unique(tuple(keys), self.key, "starter keys")
        return tuple(starters)

    def validate_project(self, value: object) -> ViewProject:
        if not isinstance(value, ViewProject):
            raise _error(self.key, "requires a ViewProject record")
        if value.provider != self.key:
            raise _error(self.key, f"cannot inspect project for {value.provider!r}")
        return replace(value, options=self.validate_options(value.options))

    def validate_options(self, value: object) -> Mapping[str, JsonValue]:
        if not isinstance(value, Mapping):
            raise _error(self.key, "requires options to be a mapping")
        if len(value) > _MAX_OPTIONS:
            raise _error(self.key, f"limits options to {_MAX_OPTIONS} entries")
        if any(not isinstance(name, str) for name in value):
            raise _error(self.key, "requires option names to be strings")
        normalized = _json_value(
            dict(cast(Mapping[str, object], value)),
            self.key,
            "options",
        )
        return cast(dict[str, JsonValue], normalized)

    def validate_created_files(
        self,
        starter: ProviderStarter,
        value: object,
    ) -> Mapping[PurePosixPath, bytes]:
        self.validate_starters((starter,))
        if not isinstance(value, Mapping) or not value:
            raise _error(self.key, "requires starter files")
        tracker = FileBudgetTracker(PROJECT_INPUT_BUDGET, "Provider starter")
        tracker.require_count(len(value))
        files: dict[PurePosixPath, bytes] = {}
        shapes: list[tuple[tuple[str, ...], PurePosixPath]] = []
        for raw_path, payload in value.items():
            path = _provider_path(raw_path, self.key, "starter file path")
            if _is_manifest(path):
                raise _error(self.key, "reserves top-level 'view.toml' for Studio")
            if type(payload) is not bytes:
                raise _error(self.key, f"requires {path.as_posix()!r} to contain bytes")
            tracker.add(path.as_posix(), len(cast(bytes, payload)))
            shape = _path_shape(path)
            shapes.append((shape, path))
            files[path] = cast(bytes, payload)
        ordered = sorted(shapes)
        for (current_shape, current), (shape, path) in pairwise(ordered):
            shared = min(len(shape), len(current_shape))
            if shape[:shared] != current_shape[:shared]:
                continue
            relation = (
                "case-colliding" if len(shape) == len(current_shape) else "overlapping"
            )
            raise _error(
                self.key,
                f"returned {relation} starter paths "
                f"{current.as_posix()!r} and {path.as_posix()!r}",
            )
        missing = sorted(set(starter.documents) - files.keys())
        if missing:
            raise _error(
                self.key,
                f"starter omits document {missing[0].as_posix()!r}",
            )
        return MappingProxyType(files)

    def validate_inspection(
        self,
        project: object,
        value: object,
    ) -> ProjectInspection:
        self.validate_project(project)
        if not isinstance(value, ProjectInspection):
            raise _error(self.key, "requires a ProjectInspection record")
        documents = _tuple(
            value.editor_documents,
            self.key,
            "editor documents",
            maximum=_MAX_DOCUMENTS,
        )
        document_paths: list[PurePosixPath] = []
        for item in documents:
            if not isinstance(item, SourceDocument):
                raise _error(self.key, "requires SourceDocument records")
            path = _provider_path(item.path, self.key, "editor document path")
            if _is_manifest(path):
                raise _error(
                    self.key,
                    "cannot expose Studio-owned 'view.toml' in the editor",
                )
            document_paths.append(path)
            _text(item.language, self.key, "editor document language")
            if item.access not in {"edit", "read"}:
                raise _error(self.key, "returned invalid editor document access")
            if item.label is not None:
                _text(item.label, self.key, "editor document label")
        _unique(tuple(document_paths), self.key, "editor document paths")
        _validate_casefold_unique_paths(
            tuple(document_paths),
            self.key,
            "editor document paths",
        )
        scope: list[ProjectInput] = []
        for item in _tuple(
            value.input_scope,
            self.key,
            "input scope",
            maximum=_MAX_INPUT_SCOPE,
        ):
            if not isinstance(item, ProjectInput) or item.kind not in {
                "file",
                "directory",
            }:
                raise _error(self.key, "requires ProjectInput records")
            scope.append(
                ProjectInput(
                    _input_path(item.path, self.key, item.kind),
                    item.kind,
                )
            )
        normalized_scope = tuple(scope)
        _validate_non_overlapping_scope(normalized_scope, self.key)

        def covered(path: PurePosixPath) -> bool:
            return any(
                item.path == path if item.kind == "file" else _contains(item.path, path)
                for item in scope
            )

        manifest = _MANIFEST_PATH
        if not covered(manifest):
            raise _error(
                self.key,
                "must include Studio-owned 'view.toml' in its input scope",
            )
        missing_documents = tuple(path for path in document_paths if not covered(path))
        if missing_documents:
            missing = min(missing_documents)
            raise _error(
                self.key,
                f"editor document {missing.as_posix()!r} is outside the input scope",
            )
        document_set = set(document_paths)
        diagnostic_sources = {*document_set, manifest}
        diagnostic_bytes = 0
        for diagnostic in _tuple(
            value.diagnostics,
            self.key,
            "diagnostics",
            maximum=_MAX_DIAGNOSTICS,
        ):
            try:
                validated = validate_project_diagnostic(
                    diagnostic,
                    documents=diagnostic_sources,
                )
            except ValueError as error:
                raise _error(self.key, str(error)) from error
            diagnostic_bytes += len(
                (
                    validated.code
                    + validated.message
                    + validated.hint
                    + (validated.source.path.as_posix() if validated.source else "")
                ).encode("utf-8")
            )
            if diagnostic_bytes > _MAX_DIAGNOSTIC_BYTES:
                raise _error(
                    self.key,
                    f"limits diagnostics to {_MAX_DIAGNOSTIC_BYTES} encoded bytes",
                )
        sites = []
        mount_bytes = 0
        for site in _tuple(
            value.mounts,
            self.key,
            "projection sites",
            maximum=_MAX_MOUNTS,
        ):
            try:
                validated_site = validate_mount_declaration(
                    site,
                    documents=document_set,
                )
            except ValueError as error:
                raise _error(self.key, str(error)) from error
            mount_bytes += len(
                json.dumps(
                    validated_site.to_dict(),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
            )
            if mount_bytes > _MAX_MOUNT_BYTES:
                raise _error(
                    self.key,
                    f"limits projection sites to {_MAX_MOUNT_BYTES} encoded bytes",
                )
            sites.append(validated_site)
        _unique(tuple(site.id for site in sites), self.key, "projection site IDs")
        _text(value.build_fingerprint, self.key, "build fingerprint")
        return replace(value, input_scope=normalized_scope)

    def validate_inspection_request(self, value: object) -> InspectionRequest:
        if not isinstance(value, InspectionRequest):
            raise _error(self.key, "requires an InspectionRequest record")
        project = self.validate_project(value.project)
        cache = _core_path(value.cache_root, self.key, "inspection cache root")
        if _overlap(cache, project.root):
            raise _error(
                self.key,
                "requires inspection cache outside the view project",
            )
        if cache.exists() and not cache.is_dir():
            raise _error(self.key, "requires inspection cache root to be a directory")
        if not isinstance(value.cancellation, ProviderCancellation):
            raise _error(self.key, "requires a ProviderCancellation owner")
        if not callable(getattr(value.runner, "run", None)):
            raise _error(self.key, "requires a supervised provider runner")
        if (
            not isinstance(value.command_timeout, (int, float))
            or isinstance(value.command_timeout, bool)
            or not math.isfinite(value.command_timeout)
            or value.command_timeout <= 0
        ):
            raise _error(
                self.key,
                "requires a positive finite inspection command budget",
            )
        return replace(value, project=project, cache_root=cache)

    def validate_build_request(self, value: object) -> BuildRequest:
        if not isinstance(value, BuildRequest):
            raise _error(self.key, "requires a BuildRequest record")
        project = self.validate_project(value.project)
        inspection = self.validate_inspection(project, value.inspection)
        self.validate_profile(value.profile)
        inputs = tuple(
            _provider_path(item, self.key, "build input path")
            for item in _tuple(
                value.inputs,
                self.key,
                "build inputs",
                maximum=_MAX_INPUT_SCOPE,
            )
        )
        _unique(inputs, self.key, "build input paths")
        if not inputs:
            raise _error(self.key, "requires enumerated build inputs")
        snapshot = _core_path(project.root, self.key, "snapshot root")
        staging = _core_path(value.staging_root, self.key, "staging root")
        cache = _core_path(value.cache_root, self.key, "cache root")
        if not staging.is_dir():
            raise _error(self.key, "requires an existing staging directory")
        if cache.name != ".cache" or cache.parent.name != ".artifacts":
            raise _error(self.key, "requires cache root to end with .artifacts/.cache")
        if cache.exists() and not cache.is_dir():
            raise _error(self.key, "requires cache root to be a directory")
        if _overlap(cache, snapshot) or _overlap(cache, staging):
            raise _error(self.key, "requires cache outside snapshot and staging roots")
        if not isinstance(value.cancellation, ProviderCancellation):
            raise _error(self.key, "requires a ProviderCancellation owner")
        if not callable(getattr(value.runner, "run", None)):
            raise _error(self.key, "requires a supervised provider runner")
        if (
            not isinstance(value.command_timeout, (int, float))
            or isinstance(value.command_timeout, bool)
            or not math.isfinite(value.command_timeout)
            or value.command_timeout <= 0
        ):
            raise _error(self.key, "requires a positive finite build command budget")
        _text(value.project_revision, self.key, "project revision")
        return replace(
            value,
            project=project,
            inspection=inspection,
            inputs=inputs,
        )

    def validate_build_result(
        self,
        request: BuildRequest,
        value: object,
    ) -> BuildResult:
        if not isinstance(value, BuildResult):
            raise _error(self.key, "requires a BuildResult record")
        documents = {
            *(item.path for item in request.inspection.editor_documents),
            _MANIFEST_PATH,
        }
        diagnostics: list[ProjectDiagnostic] = []
        diagnostic_bytes = 0
        for item in _tuple(
            value.diagnostics,
            self.key,
            "build diagnostics",
            maximum=_MAX_DIAGNOSTICS,
        ):
            try:
                diagnostic = validate_project_diagnostic(item, documents=documents)
            except ValueError as error:
                raise _error(self.key, str(error)) from error
            diagnostic_bytes += len(
                (
                    diagnostic.code
                    + diagnostic.message
                    + diagnostic.hint
                    + (diagnostic.source.path.as_posix() if diagnostic.source else "")
                ).encode("utf-8")
            )
            if diagnostic_bytes > _MAX_DIAGNOSTIC_BYTES:
                raise _error(
                    self.key,
                    "limits build diagnostics to "
                    f"{_MAX_DIAGNOSTIC_BYTES} encoded bytes",
                )
            diagnostics.append(diagnostic)
        normalized_diagnostics = tuple(diagnostics)
        if value.document is None:
            if not any(item.severity == "error" for item in normalized_diagnostics):
                raise _error(self.key, "returned no document or error diagnostic")
            return replace(value, diagnostics=normalized_diagnostics)
        document = _provider_path(value.document, self.key, "build document")
        if not request.staging_root.joinpath(*document.parts).is_file():
            raise _error(
                self.key,
                f"returned missing build document {document.as_posix()!r}",
            )
        return replace(value, document=document, diagnostics=normalized_diagnostics)

    def validate_profile(self, value: object) -> BuildProfile:
        if not isinstance(value, str) or value not in _PROFILES:
            raise _error(self.key, f"does not support build profile {value!r}")
        return cast(BuildProfile, value)

    def provenance(self, inspection: ProjectInspection) -> ProviderProvenance:
        """Return compact versioned provenance for a normalized inspection."""
        payload = json.dumps(
            [
                self.distribution,
                self.version,
                self.key,
                self.info.api_version,
                _BUILD_CONTRACT_VERSION,
                inspection.build_fingerprint,
            ],
            separators=(",", ":"),
        ).encode()
        return ProviderProvenance(
            key=self.key,
            distribution=self.distribution,
            version=self.version,
            api_version=self.info.api_version,
            build_fingerprint=f"sha256:{hashlib.sha256(payload).hexdigest()}",
        )
