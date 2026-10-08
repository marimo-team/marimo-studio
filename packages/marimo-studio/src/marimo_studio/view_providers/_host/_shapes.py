"""Check provider record shapes: text, JSON, paths, and bounded collections."""

from __future__ import annotations

import json
import math
from collections.abc import Iterable
from itertools import pairwise
from pathlib import Path, PurePosixPath
from typing import cast

from marimo_studio._filesystem.paths import validate_relative_path
from marimo_studio.errors import ConfigurationError
from marimo_studio.view_providers import JsonValue
from marimo_studio.view_providers._validation import (
    MAX_PROVIDER_TEXT_BYTES,
    MAX_SAFE_INTEGER,
)

MANIFEST_PATH = PurePosixPath("view.toml")
MAX_DOCUMENTS = 256
_RESERVED_ROOTS = frozenset({".artifacts", ".gitignore", ".locks"})
_MAX_JSON_BYTES = 64 * 1024
_MAX_JSON_DEPTH = 32
_MAX_JSON_NODES = 4_096


def is_manifest(path: PurePosixPath) -> bool:
    return path.as_posix().casefold() == MANIFEST_PATH.as_posix()


def conformance_error(provider: str, message: str) -> ConfigurationError:
    return ConfigurationError(f"View provider {provider!r} {message}")


def checked_text(value: object, provider: str, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise conformance_error(provider, f"requires {field} to be a non-empty string")
    if len(value.encode("utf-8")) > MAX_PROVIDER_TEXT_BYTES:
        raise conformance_error(
            provider, f"requires {field} to fit within {MAX_PROVIDER_TEXT_BYTES} bytes"
        )
    return value


def checked_tuple(
    value: object,
    provider: str,
    field: str,
    *,
    maximum: int,
) -> tuple[object, ...]:
    if not isinstance(value, tuple):
        raise conformance_error(provider, f"requires {field} to be a tuple")
    if len(value) > maximum:
        raise conformance_error(provider, f"limits {field} to {maximum} records")
    return value


def require_unique(values: tuple[object, ...], provider: str, field: str) -> None:
    if len(values) != len(set(values)):
        raise conformance_error(provider, f"requires unique {field}")


def checked_json(value: object, provider: str, field: str) -> JsonValue:
    nodes = 0

    def normalize_json(item: object, depth: int) -> JsonValue:
        nonlocal nodes
        nodes += 1
        if nodes > _MAX_JSON_NODES:
            raise conformance_error(
                provider, f"limits {field} to {_MAX_JSON_NODES} JSON values"
            )
        if depth > _MAX_JSON_DEPTH:
            raise conformance_error(
                provider, f"limits {field} to {_MAX_JSON_DEPTH} JSON levels"
            )
        if item is None or type(item) is bool:
            return cast(JsonValue, item)
        if type(item) is int:
            if abs(cast(int, item)) > MAX_SAFE_INTEGER:
                raise conformance_error(
                    provider, f"requires browser-safe integers in {field}"
                )
            return cast(JsonValue, item)
        if type(item) is str:
            if len(item.encode("utf-8")) > MAX_PROVIDER_TEXT_BYTES:
                raise conformance_error(
                    provider, f"requires strings in {field} to be bounded"
                )
            return cast(JsonValue, item)
        if type(item) is float:
            if not math.isfinite(cast(float, item)):
                raise conformance_error(provider, f"requires finite numbers in {field}")
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
        raise conformance_error(provider, f"requires JSON-compatible values in {field}")

    normalized = normalize_json(value, 0)
    encoded = json.dumps(
        normalized,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(encoded) > _MAX_JSON_BYTES:
        raise conformance_error(
            provider, f"limits {field} to {_MAX_JSON_BYTES} encoded bytes"
        )
    return normalized


def provider_path(value: object, provider: str, field: str) -> PurePosixPath:
    if type(value) is not PurePosixPath:
        raise conformance_error(provider, f"requires {field} to be a PurePosixPath")
    try:
        path = validate_relative_path(value, field=field)
    except ValueError as error:
        raise conformance_error(provider, str(error)) from error
    if len(path.as_posix().encode("utf-8")) > MAX_PROVIDER_TEXT_BYTES:
        raise conformance_error(
            provider, f"requires {field} to fit within {MAX_PROVIDER_TEXT_BYTES} bytes"
        )
    if path.parts[0].casefold() in {name.casefold() for name in _RESERVED_ROOTS}:
        raise conformance_error(
            provider, f"reserves top-level {path.parts[0]!r} for Studio"
        )
    return path


def input_path(value: object, provider: str, kind: str) -> PurePosixPath:
    if (
        kind == "directory"
        and type(value) is PurePosixPath
        and value == PurePosixPath(".")
    ):
        return value
    return provider_path(value, provider, "build input path")


def contains(root: PurePosixPath, path: PurePosixPath) -> bool:
    return root == PurePosixPath(".") or root == path or root in path.parents


def path_shape(path: PurePosixPath) -> tuple[str, ...]:
    if path == PurePosixPath("."):
        return ()
    return tuple(part.casefold() for part in path.parts)


def require_casefold_unique(
    paths: tuple[PurePosixPath, ...],
    provider: str,
    field: str,
) -> None:
    ordered = sorted((path_shape(path), path.as_posix()) for path in paths)
    for (current_shape, current), (shape, path) in pairwise(ordered):
        if shape == current_shape:
            raise conformance_error(
                provider,
                f"returned case-colliding {field} {current!r} and {path!r}",
            )


def require_disjoint_paths(
    paths: Iterable[PurePosixPath],
    provider: str,
    label: str,
) -> None:
    """Reject paths that collide by case or where one path contains another."""
    ordered = sorted(
        (path_shape(path), index, path) for index, path in enumerate(paths)
    )
    for (current_shape, _, current), (shape, _, path) in pairwise(ordered):
        shared = min(len(shape), len(current_shape))
        if shape[:shared] != current_shape[:shared]:
            continue
        relation = (
            "case-colliding" if len(shape) == len(current_shape) else "overlapping"
        )
        raise conformance_error(
            provider,
            f"returned {relation} {label} paths "
            f"{current.as_posix()!r} and {path.as_posix()!r}",
        )


def core_path(value: object, provider: str, field: str) -> Path:
    if not isinstance(value, Path) or not value.is_absolute():
        raise conformance_error(provider, f"requires {field} to be an absolute path")
    return value


def overlaps(first: Path, second: Path) -> bool:
    return first == second or first in second.parents or second in first.parents
