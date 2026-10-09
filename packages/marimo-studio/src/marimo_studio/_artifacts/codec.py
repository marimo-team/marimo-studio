"""Strict JSON codecs for immutable artifacts and profile receipts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Literal, NoReturn, cast

from marimo_export.values import MAX_ACCEPTED_MEDIA_TYPES, Size

from marimo_studio._artifacts.limits import ARTIFACT_OUTPUT_BUDGET
from marimo_studio._artifacts.paths import normalized_artifact_path, read_secure_bytes
from marimo_studio._artifacts.records import (
    ArtifactFile,
    ArtifactManifest,
    ArtifactProfileState,
    ArtifactPublication,
    ArtifactTemplate,
    ViewBuildPhase,
    ViewBuildState,
)
from marimo_studio._workspace.models import RESERVED_VIEW_ASSET_NAMES
from marimo_studio.errors import ConfigurationError
from marimo_studio.view_providers import (
    BuildProfile,
    ProjectDiagnostic,
    ProjectionKind,
    SourceLocation,
)
from marimo_studio.view_providers._artifact_sites import ArtifactSite
from marimo_studio.view_providers._host.records import ProviderProvenance
from marimo_studio.view_providers._targets import MAX_CELL_TARGETS
from marimo_studio.view_providers._validation import (
    validate_artifact_site,
    validate_project_diagnostic,
)

_PROFILES = frozenset({"development", "production"})
_PHASES = frozenset({"unbuilt", "building", "failed", "published", "stale"})
_CONTROL_FILE_MAX_BYTES = 16 * 1024 * 1024


class ArtifactFormatError(ConfigurationError):
    """Stored artifact state was written in another Studio format."""


def _invalid(message: str) -> NoReturn:
    raise ConfigurationError(message)


def _require_schema(value: object, schema: int, label: str) -> None:
    # Read the schema before the fields, so a record from another Studio
    # version reads as a format change and a damaged record reads as damage.
    found = value.get("schema") if isinstance(value, dict) else None
    if type(found) is int and found != schema:
        raise ArtifactFormatError(
            f"{label} uses schema {found}, and this Studio version reads "
            f"schema {schema}"
        )


def _object(value: object, fields: set[str], label: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        _invalid(f"{label} must be a JSON object")
    data = cast(dict[str, object], value)
    if set(data) != fields:
        _invalid(f"{label} has invalid fields")
    return data


def _array(
    value: object,
    label: str,
    *,
    maximum: int | None = None,
) -> list[object]:
    if not isinstance(value, list):
        _invalid(f"{label} must be a JSON array")
    items = cast(list[object], value)
    if maximum is not None and len(items) > maximum:
        _invalid(f"{label} exceeds the {maximum}-record limit")
    return items


def _string(value: object, label: str, *, empty: bool = False) -> str:
    if not isinstance(value, str) or (not empty and not value):
        _invalid(f"{label} must be a {'string' if empty else 'non-empty string'}")
    return value


def _string_array(
    value: object,
    label: str,
    *,
    maximum: int | None = None,
) -> tuple[str, ...]:
    return tuple(
        _string(item, f"{label} entry")
        for item in _array(value, label, maximum=maximum)
    )


def _integer(value: object, label: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        _invalid(f"{label} must be an integer greater than or equal to {minimum}")
    return value


def _revision(value: object, label: str) -> str:
    revision = _string(value, label)
    prefix = "sha256:"
    digest = revision.removeprefix(prefix)
    if (
        not revision.startswith(prefix)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        _invalid(f"{label} must be a lowercase SHA-256 revision")
    return revision


def _sha256(value: object, label: str) -> str:
    digest = _string(value, label)
    if len(digest) != 64 or any(
        character not in "0123456789abcdef" for character in digest
    ):
        _invalid(f"{label} must be a lowercase SHA-256 digest")
    return digest


def _projection_source_location(value: object, label: str) -> SourceLocation:
    data = _object(value, {"path", "line", "column"}, label)
    line = data["line"]
    column = data["column"]
    if type(line) is not int or type(column) is not int:
        _invalid(f"{label} coordinates must be integers")
    return SourceLocation(
        PurePosixPath(_string(data["path"], f"{label} path")),
        line,
        column,
    )


def _size(value: object, label: str) -> Size | None:
    if value is None:
        return None
    data = _object(value, {"width", "height"}, label)
    width, height = data["width"], data["height"]
    try:
        return Size(cast(float, width), cast("float | None", height))
    except (TypeError, ValueError) as error:
        _invalid(f"{label} is invalid: {error}")


def _artifact_site(value: object, label: str) -> ArtifactSite:
    data = _object(value, {"id", "kind", "source", "targets", "accept", "size"}, label)
    kind = _string(data["kind"], f"{label} kind")
    raw_targets = data["targets"]
    targets = (
        None
        if raw_targets is None
        else _string_array(
            raw_targets,
            f"{label} targets",
            maximum=MAX_CELL_TARGETS,
        )
    )
    site = ArtifactSite(
        id=_string(data["id"], f"{label} id"),
        kind=cast(ProjectionKind, kind),
        source=_projection_source_location(data["source"], f"{label} source"),
        targets=targets,
        accept=_string_array(
            data["accept"], f"{label} accept", maximum=MAX_ACCEPTED_MEDIA_TYPES
        ),
        size=_size(data["size"], f"{label} size"),
    )
    try:
        return validate_artifact_site(site)
    except ValueError as error:
        raise ConfigurationError(str(error)) from error


def _provider_provenance(
    value: object,
    label: str = "Artifact provider",
) -> ProviderProvenance:
    data = _object(
        value,
        {
            "key",
            "distribution",
            "version",
            "build_fingerprint",
        },
        label,
    )
    return ProviderProvenance(
        key=_string(data["key"], f"{label} key"),
        distribution=_string(data["distribution"], f"{label} distribution"),
        version=_string(data["version"], f"{label} version"),
        build_fingerprint=_revision(
            data["build_fingerprint"],
            f"{label} build fingerprint",
        ),
    )


def _diagnostic(value: object, label: str) -> ProjectDiagnostic:
    data = _object(value, {"code", "severity", "message", "hint", "source"}, label)
    severity = _string(data["severity"], f"{label} severity")
    source = (
        None
        if data["source"] is None
        else _projection_source_location(data["source"], f"{label} source")
    )
    diagnostic = ProjectDiagnostic(
        code=_string(data["code"], f"{label} code"),
        severity=cast(Literal["warning", "error"], severity),
        message=_string(data["message"], f"{label} message", empty=True),
        hint=_string(data["hint"], f"{label} hint", empty=True),
        source=source,
    )
    try:
        return validate_project_diagnostic(diagnostic)
    except ValueError as error:
        raise ConfigurationError(str(error)) from error


def _file_records(files: tuple[ArtifactFile, ...]) -> list[dict[str, object]]:
    return [
        {"path": item.path.as_posix(), "sha256": item.sha256, "size": item.size}
        for item in files
    ]


def _artifact_identity(
    document: str,
    files: tuple[ArtifactFile, ...],
    sites: tuple[ArtifactSite, ...],
    template: ArtifactTemplate | None = None,
) -> dict[str, object]:
    identity: dict[str, object] = {
        "schema": 3,
        "document": document,
        "files": _file_records(files),
        "sites": [item.to_dict() for item in sites],
    }
    if template is not None:
        identity["template"] = {
            "document": template.document.as_posix(),
            "files": _file_records(template.files),
            "renderer": template.renderer,
        }
    return identity


def artifact_revision(
    document: str,
    files: tuple[ArtifactFile, ...],
    sites: tuple[ArtifactSite, ...],
    template: ArtifactTemplate | None = None,
) -> str:
    encoded = json.dumps(
        _artifact_identity(document, files, sites, template),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def artifact_manifest(
    document: object,
    files: tuple[ArtifactFile, ...],
    sites: tuple[ArtifactSite, ...],
    template: ArtifactTemplate | None = None,
) -> ArtifactManifest:
    path = normalized_artifact_path(document, "Artifact document path")
    if path not in {item.path for item in files}:
        _invalid("Artifact document is not present in its file manifest")
    if any(
        item.path.parts[0].casefold() in RESERVED_VIEW_ASSET_NAMES for item in files
    ):
        _invalid("Artifact file manifest uses a reserved Studio route")
    if len({item.path for item in files}) != len(files):
        _invalid("Artifact file manifest contains duplicate paths")
    if tuple(sorted(files, key=lambda item: item.path.as_posix())) != files:
        _invalid("Artifact file manifest must use canonical path order")
    if len(
        {tuple(part.casefold() for part in item.path.parts) for item in files}
    ) != len(files):
        _invalid("Artifact file manifest contains case-equivalent paths")
    if len({site.id for site in sites}) != len(sites):
        _invalid("Artifact projection sites must have unique IDs")
    if template is not None and template.document not in {
        item.path for item in template.files
    }:
        _invalid("Artifact template document is not present in its file manifest")
    revision = artifact_revision(path.as_posix(), files, sites, template)
    return ArtifactManifest(revision, path, files, sites, template)


def artifact_manifest_dict(manifest: ArtifactManifest) -> dict[str, object]:
    return {
        **_artifact_identity(
            manifest.document.as_posix(),
            manifest.files,
            manifest.sites,
            manifest.template,
        ),
        "artifact_revision": manifest.artifact_revision,
    }


def _artifact_files(value: object, label: str) -> tuple[ArtifactFile, ...]:
    return tuple(
        ArtifactFile(
            normalized_artifact_path(item_data["path"], f"{label} path"),
            _sha256(item_data["sha256"], f"{label} digest"),
            _integer(item_data["size"], f"{label} size"),
        )
        for item in _array(value, label, maximum=ARTIFACT_OUTPUT_BUDGET.max_files)
        for item_data in [_object(item, {"path", "sha256", "size"}, label)]
    )


def decode_artifact_manifest(value: object) -> ArtifactManifest:
    _require_schema(value, 3, "Artifact manifest")
    fields = {"schema", "artifact_revision", "document", "files", "sites"}
    if isinstance(value, dict) and "template" in value:
        fields.add("template")
    data = _object(value, fields, "Artifact manifest")
    if type(data["schema"]) is not int:
        _invalid("Artifact manifest schema is invalid")
    files = _artifact_files(data["files"], "Artifact files")
    sites = tuple(
        _artifact_site(item, "Artifact projection site")
        for item in _array(data["sites"], "Artifact projection sites", maximum=512)
    )
    template = None
    if "template" in data:
        template_data = _object(
            data["template"],
            {"document", "files", "renderer"},
            "Artifact template",
        )
        template = ArtifactTemplate(
            normalized_artifact_path(
                template_data["document"],
                "Artifact template document",
            ),
            _artifact_files(template_data["files"], "Artifact template files"),
            _string(template_data["renderer"], "Artifact template renderer"),
        )
    manifest = artifact_manifest(
        data["document"],
        files,
        sites,
        template,
    )
    if (
        _revision(data["artifact_revision"], "Artifact revision")
        != manifest.artifact_revision
    ):
        _invalid("Artifact manifest digest does not match its content")
    return manifest


def _publication(value: object) -> ArtifactPublication:
    data = _object(
        value,
        {
            "project_revision",
            "artifact_revision",
            "provider",
            "diagnostics",
            "duration_ms",
        },
        "Artifact publication",
    )
    publication = ArtifactPublication(
        _revision(data["project_revision"], "Published project revision"),
        _revision(data["artifact_revision"], "Published artifact revision"),
        _provider_provenance(data["provider"]),
        tuple(
            _diagnostic(item, "Published build diagnostic")
            for item in _array(
                data["diagnostics"],
                "Published build diagnostics",
                maximum=512,
            )
        ),
        _integer(data["duration_ms"], "Published build duration"),
    )
    if any(item.severity == "error" for item in publication.diagnostics):
        _invalid("Published build diagnostics cannot contain errors")
    return publication


def profile_state(
    profile: BuildProfile,
    published: ArtifactPublication | None,
    build: ViewBuildState,
) -> ArtifactProfileState:
    if build.profile != profile:
        _invalid("Artifact build receipt targets another profile")
    if published is None and build.artifact_revision is not None:
        _invalid("Artifact build receipt references an unpublished artifact")
    if published is not None and build.artifact_revision != published.artifact_revision:
        _invalid("Artifact build receipt and publication revisions differ")
    if build.phase == "published" and (
        published is None
        or build.project_revision != published.project_revision
        or build.diagnostics != published.diagnostics
        or build.duration_ms != published.duration_ms
    ):
        _invalid("Published artifact build receipt does not match its publication")
    return ArtifactProfileState(profile, published, build)


def profile_state_dict(state: ArtifactProfileState) -> dict[str, object]:
    return {
        "schema": 2,
        "profile": state.profile,
        "published": (
            {
                "project_revision": state.published.project_revision,
                "artifact_revision": state.published.artifact_revision,
                "provider": state.published.provider.to_dict(),
                "diagnostics": [item.to_dict() for item in state.published.diagnostics],
                "duration_ms": state.published.duration_ms,
            }
            if state.published is not None
            else None
        ),
        "build": {
            "phase": state.build.phase,
            "project_revision": state.build.project_revision,
            "artifact_revision": state.build.artifact_revision,
            "diagnostics": [item.to_dict() for item in state.build.diagnostics],
            "duration_ms": state.build.duration_ms,
        },
    }


def decode_profile_state(
    value: object, expected_profile: BuildProfile
) -> ArtifactProfileState:
    _require_schema(value, 2, "Artifact profile")
    data = _object(
        value, {"schema", "profile", "published", "build"}, "Artifact profile"
    )
    if type(data["schema"]) is not int or data["profile"] != expected_profile:
        _invalid("Artifact profile identity is invalid")
    raw_build = _object(
        data["build"],
        {
            "phase",
            "project_revision",
            "artifact_revision",
            "diagnostics",
            "duration_ms",
        },
        "Artifact build receipt",
    )
    phase = _string(raw_build["phase"], "Artifact build phase")
    if phase not in _PHASES:
        _invalid("Artifact build phase is invalid")
    project_value = raw_build["project_revision"]
    artifact_value = raw_build["artifact_revision"]
    duration_value = raw_build["duration_ms"]
    build = ViewBuildState(
        profile=expected_profile,
        phase=cast(ViewBuildPhase, phase),
        project_revision=(
            None
            if project_value is None
            else _revision(project_value, "Artifact build project revision")
        ),
        artifact_revision=(
            None
            if artifact_value is None
            else _revision(artifact_value, "Artifact build revision")
        ),
        diagnostics=tuple(
            _diagnostic(item, "Artifact build diagnostic")
            for item in _array(
                raw_build["diagnostics"],
                "Artifact build diagnostics",
                maximum=512,
            )
        ),
        duration_ms=(
            None
            if duration_value is None
            else _integer(duration_value, "Artifact build duration")
        ),
    )
    published = None if data["published"] is None else _publication(data["published"])
    return profile_state(expected_profile, published, build)


def read_json(root: Path, path: Path, label: str) -> object:
    def reject_constant(value: str) -> NoReturn:
        _invalid(f"{label} contains non-finite JSON value {value}")

    def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, item in pairs:
            if key in value:
                _invalid(f"{label} contains duplicate field {key!r}")
            value[key] = item
        return value

    try:
        return json.loads(
            read_secure_bytes(
                root,
                path,
                label,
                max_bytes=_CONTROL_FILE_MAX_BYTES,
            ).decode("utf-8"),
            parse_constant=reject_constant,
            object_pairs_hook=unique_object,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ConfigurationError(f"Could not read {label}: {path}: {error}") from error


def encode_json(value: object, *, pretty: bool = False) -> str:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2 if pretty else None,
            separators=None if pretty else (",", ":"),
            allow_nan=False,
        )
        + "\n"
    )
