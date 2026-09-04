"""Locate and validate the packaged browser runtime."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path, PurePosixPath

from marimo_studio.errors import ProtocolError
from marimo_studio.errors._internal import CompatibilityError

_ENTRY_CLOSURES = "entry-closures.json"
_FORBIDDEN_ZERO_PYTHON_PART = re.compile(
    r"(?:^|[^a-z0-9])"
    r"(code-source|notebook(?:-code|-source)?|pyodide|server|source-code|wasm|websocket|worker)"
    r"(?:[^a-z0-9]|$)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class BrowserEntryClosure:
    """Files required to serve one built browser entrypoint."""

    script: Path
    styles: tuple[Path, ...]
    assets: tuple[Path, ...]
    manifest: Path
    file_count: int
    total_bytes: int


def runtime_assets_path() -> Path:
    return Path(str(files("marimo_studio").joinpath("_static").joinpath("browser")))


def browser_entry_closure(name: str) -> BrowserEntryClosure:
    """Return the validated transitive file closure for a browser entry."""
    root = runtime_assets_path()
    manifest = root / _ENTRY_CLOSURES
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("schema") != 1:
            raise ValueError("schema must be 1")
        entries = payload.get("entries")
        if not isinstance(entries, dict) or name not in entries:
            raise ValueError(f"entry {name!r} is unavailable")
        entry = entries[name]
        if not isinstance(entry, dict) or set(entry) != {
            "script",
            "styles",
            "assets",
        }:
            raise ValueError(f"entry {name!r} has invalid fields")
        script = _closure_path(root, entry["script"], f"{name}.script")
        styles = _closure_paths(root, entry["styles"], f"{name}.styles")
        assets = _closure_paths(root, entry["assets"], f"{name}.assets")
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        raise ProtocolError(
            f"Invalid browser entry closure at {manifest}: {error}"
        ) from error

    paths = (script, *styles, *assets)
    if len(paths) != len(set(paths)):
        raise ProtocolError(f"Browser entry closure {name!r} contains duplicate paths")
    if script.suffix != ".js":
        raise ProtocolError(f"Browser entry closure {name!r} script must use .js")
    if any(style.suffix != ".css" for style in styles):
        raise ProtocolError(f"Browser entry closure {name!r} styles must use .css")
    if name == "runtime":
        zero_python = next(
            (
                path.relative_to(root).as_posix()
                for path in paths
                if any(
                    part.startswith("zero-python")
                    for part in path.relative_to(root).parts
                )
            ),
            None,
        )
        if zero_python is not None:
            raise ProtocolError(
                "WebAssembly browser entry includes Zero-Python runtime asset "
                f"{zero_python!r}"
            )
    if name == "zero-python":
        forbidden = next(
            (
                path.relative_to(root).as_posix()
                for path in paths
                if _FORBIDDEN_ZERO_PYTHON_PART.search(path.relative_to(root).as_posix())
            ),
            None,
        )
        if forbidden is not None:
            raise ProtocolError(
                "Zero-Python browser entry includes forbidden runtime asset "
                f"{forbidden!r}"
            )
    try:
        total_bytes = sum(path.stat().st_size for path in paths)
    except OSError as error:
        raise ProtocolError(
            f"Browser entry closure {name!r} changed while it was inspected"
        ) from error
    return BrowserEntryClosure(
        script=script,
        styles=styles,
        assets=assets,
        manifest=manifest,
        file_count=len(paths),
        total_bytes=total_bytes,
    )


def _closure_paths(root: Path, value: object, field: str) -> tuple[Path, ...]:
    if not isinstance(value, list):
        raise TypeError(f"{field} must be an array")
    return tuple(
        _closure_path(root, item, f"{field}[{index}]")
        for index, item in enumerate(value)
    )


def _closure_path(root: Path, value: object, field: str) -> Path:
    if not isinstance(value, str) or not value:
        raise TypeError(f"{field} must be a non-empty path")
    relative = PurePosixPath(value)
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or "." in relative.parts
        or "\\" in value
        or ":" in value
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
        or relative.as_posix() != value
    ):
        raise ValueError(f"{field} must be a normalized relative POSIX path")
    path = root.joinpath(*relative.parts)
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise ValueError(f"{field} must not traverse a symlink")
    if not path.is_file():
        raise ValueError(f"{field} does not name a packaged file")
    return path


def validate_runtime_marimo_release(
    *,
    version: str,
    commit: str,
    patch_sha256: str,
) -> None:
    """Validate packaged browser assets against the pinned Marimo release."""
    observed = _runtime_marimo_metadata()
    expected = {
        "version": version,
        "commit": commit,
        "patchSha256": patch_sha256,
    }
    if observed != expected:
        raise CompatibilityError(
            "The packaged browser runtime does not match the pinned Marimo "
            f"release. Observed {observed!r}, expected {expected!r}."
        )


def runtime_marimo_version() -> str:
    """Return the Marimo version embedded in the packaged browser runtime."""

    return _runtime_marimo_metadata()["version"]


def _runtime_marimo_metadata() -> dict[str, str]:
    path = runtime_assets_path() / "build-meta.json"
    try:
        marimo = json.loads(path.read_text(encoding="utf-8"))["marimo"]
        metadata = {key: marimo[key] for key in ("version", "commit", "patchSha256")}
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise ProtocolError(
            f"Invalid browser runtime metadata at {path}: {error}"
        ) from error
    if not all(isinstance(value, str) and value for value in metadata.values()):
        raise ProtocolError(f"Invalid browser runtime metadata at {path}")
    return metadata
