"""Locate and validate the packaged browser runtime."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path, PurePosixPath
from typing import TypeGuard

from marimo_studio.errors import ProtocolError
from marimo_studio.errors._internal import CompatibilityError

_BUILD_META = "build-meta.json"
_BUILD_SOURCES = "build-sources.json"
_SHA256 = re.compile(r"[0-9a-f]{64}")
_ENTRY_CLOSURES = "entry-closures.json"
_SOURCE_OUTPUT = PurePosixPath(
    "packages/marimo-studio/src/marimo_studio/_static/browser"
)
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
                f"Browser runtime entry includes Prepared runtime asset {zero_python!r}"
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
                f"Prepared runtime entry includes forbidden runtime asset {forbidden!r}"
            )
    return BrowserEntryClosure(
        script=script,
        styles=styles,
        assets=assets,
        manifest=manifest,
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
    """Validate packaged browser assets against the pinned Marimo release.

    A source checkout that has never run the browser build has no assets, and
    the error names the command that builds them.
    """
    root = runtime_assets_path()
    if not (root / _BUILD_META).is_file():
        checkout = _source_checkout(root.resolve())
        if checkout is not None:
            raise ProtocolError(
                "Studio's browser assets are not built in this checkout. "
                f"Run `make setup` in {checkout} to build them."
            )
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


def validate_runtime_sources() -> None:
    """Reject a source checkout's browser assets once their sources changed.

    The browser build records digests of the files that shaped it in
    ``build-sources.json`` beside the served asset directory, together with
    that directory's path in the workspace. Assets elsewhere, such as an
    installed package, are not compared. Digests cover content with LF line
    endings, so assets built on one platform match a checkout that Git
    converted to CRLF.
    """
    root = runtime_assets_path()
    path = root.parent / _BUILD_SOURCES
    invalid = ProtocolError(
        f"Invalid browser build sources at {path}. Run `make build` to rewrite them."
    )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return
    except (OSError, ValueError) as error:
        raise invalid from error
    output = payload.get("output") if isinstance(payload, dict) else None
    if not _is_relative_posix(output):
        raise invalid
    browser = root.resolve()
    parts = PurePosixPath(output).parts
    if browser.parts[-len(parts) :] != parts:
        return
    workspace = browser.parents[len(parts) - 1]
    if not (workspace / "pnpm-workspace.yaml").is_file():
        return
    sources = payload.get("files")
    if not (
        type(payload.get("schema")) is int
        and payload["schema"] == 1
        and isinstance(sources, dict)
        and all(
            _is_relative_posix(source)
            and isinstance(digest, str)
            and _SHA256.fullmatch(digest) is not None
            for source, digest in sources.items()
        )
    ):
        raise invalid
    changed = [
        source
        for source, digest in sources.items()
        if _file_sha256(workspace / source) != digest
    ]
    if changed:
        others = len(changed) - 1
        files = changed[0] + (
            ""
            if others == 0
            else f" and {others} other file{'s' if others > 1 else ''}"
        )
        raise ProtocolError(
            "Studio's browser assets do not match this checkout: "
            f"{files} changed since the last build. "
            f"Run `make build` in {workspace} to rebuild them."
        )


def _source_checkout(browser: Path) -> Path | None:
    """Return the workspace whose browser build writes to ``browser``."""
    parts = _SOURCE_OUTPUT.parts
    if browser.parts[-len(parts) :] != parts:
        return None
    workspace = browser.parents[len(parts) - 1]
    return workspace if (workspace / "pnpm-workspace.yaml").is_file() else None


def _is_relative_posix(value: object) -> TypeGuard[str]:
    if not isinstance(value, str) or not value or "\\" in value:
        return False
    path = PurePosixPath(value)
    return (
        not path.is_absolute()
        and path.as_posix() == value
        and all(part not in {".", ".."} for part in path.parts)
    )


def _file_sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    except OSError:
        return None


def runtime_marimo_version() -> str:
    """Return the Marimo version embedded in the packaged browser runtime."""

    return _runtime_marimo_metadata()["version"]


def _runtime_marimo_metadata() -> dict[str, str]:
    path = runtime_assets_path() / _BUILD_META
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
