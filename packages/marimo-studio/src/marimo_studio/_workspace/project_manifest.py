"""Load Studio-owned view project manifests."""

from __future__ import annotations

import math
from pathlib import Path, PurePosixPath
from typing import cast

import tomlkit

from marimo_studio._filesystem.io import reject_mutable_symlinks
from marimo_studio._workspace.toml import read_toml
from marimo_studio.errors import ConfigurationError
from marimo_studio.view_providers import (
    JsonValue,
    SourceDocument,
    ViewProject,
)
from marimo_studio.view_providers._validation import validate_provider_key

VIEW_MANIFEST = "view.toml"
VIEW_MANIFEST_PATH = PurePosixPath(VIEW_MANIFEST)
VIEW_MANIFEST_DOCUMENT = SourceDocument(
    VIEW_MANIFEST_PATH,
    "toml",
    "edit",
    "View configuration",
)


def _string(value: object, field: str, path: Path) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(f"{field} must be a non-empty string in {path}")
    return value


def _json_value(value: object, field: str, path: Path) -> JsonValue:
    if value is None or type(value) in {bool, int, str}:
        return cast(JsonValue, value)
    if type(value) is float:
        if not math.isfinite(cast(float, value)):
            raise ConfigurationError(f"{field} must contain finite numbers in {path}")
        return cast(JsonValue, value)
    if type(value) is list:
        items = cast(list[object], value)
        return [_json_value(item, field, path) for item in items]
    if type(value) is dict and all(isinstance(key, str) for key in value):
        items = cast(dict[str, object], value)
        return {key: _json_value(item, field, path) for key, item in items.items()}
    raise ConfigurationError(
        f"{field} must contain JSON scalar, array, or table values in {path}"
    )


def decode_view_provider(data: dict[str, object], source: Path) -> str:
    """Return a valid provider identity from a partially invalid manifest."""
    provider = _string(data.get("provider"), "provider", source)
    try:
        validate_provider_key(provider, field="provider")
    except ValueError as error:
        raise ConfigurationError(f"{error} in {source}") from error
    return provider


def decode_view_manifest(
    data: dict[str, object],
    source: Path,
) -> tuple[str, dict[str, JsonValue]]:
    """Return the provider and explicit options from one manifest."""
    unknown = sorted(set(data) - {"schema", "provider", "options"})
    if unknown:
        raise ConfigurationError(
            f"Unsupported view manifest field {unknown[0]!r} in {source}"
        )
    schema = data.get("schema")
    if type(schema) is not int or schema != 1:
        raise ConfigurationError(f"schema must be 1 in {source}")
    provider = decode_view_provider(data, source)
    raw_options = data.get("options", {})
    if not isinstance(raw_options, dict):
        raise ConfigurationError(f"options must be a TOML table in {source}")
    options = {
        cast(str, key): _json_value(item, "options", source)
        for key, item in raw_options.items()
        if isinstance(key, str)
    }
    return provider, options


def encode_view_manifest(
    provider: str,
    options: dict[str, JsonValue] | None = None,
) -> str:
    """Serialize one core-owned view manifest."""
    validate_provider_key(provider, field="provider")
    document = tomlkit.document()
    document["schema"] = 1
    document["provider"] = provider
    if options:
        document["options"] = options
    return tomlkit.dumps(document)


def load_view_project(root: Path) -> ViewProject:
    """Load one required ``view.toml`` from a named view directory."""
    manifest = root / VIEW_MANIFEST
    reject_mutable_symlinks(root.parent, {root, manifest})
    if not manifest.is_file():
        raise ConfigurationError(f"View project manifest is missing: {manifest}")
    provider, options = decode_view_manifest(read_toml(manifest), manifest)
    return ViewProject(
        name=root.name,
        root=root.absolute(),
        manifest=manifest.absolute(),
        provider=provider,
        options=options,
    )
