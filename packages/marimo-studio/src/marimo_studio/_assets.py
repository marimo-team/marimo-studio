"""Locate and validate the packaged browser runtime."""

from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path

from marimo_studio.errors import CompatibilityError, ProtocolError


def runtime_assets_path() -> Path:
    return Path(str(files("marimo_studio").joinpath("_static", "browser")))


def validate_runtime_marimo_release(
    *,
    version: str,
    commit: str,
) -> None:
    """Validate packaged browser assets against the pinned Marimo release."""
    observed = _runtime_marimo_metadata()
    expected = {"version": version, "commit": commit}
    if observed != expected:
        raise CompatibilityError(
            "The packaged browser runtime does not match the pinned Marimo "
            f"release. Observed {observed!r}, expected {expected!r}."
        )


def _runtime_marimo_metadata() -> dict[str, str]:
    path = runtime_assets_path() / "build-meta.json"
    try:
        marimo = json.loads(path.read_text(encoding="utf-8"))["marimo"]
        metadata = {key: marimo[key] for key in ("version", "commit")}
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise ProtocolError(
            f"Invalid browser runtime metadata at {path}: {error}"
        ) from error
    if not all(isinstance(value, str) and value for value in metadata.values()):
        raise ProtocolError(f"Invalid browser runtime metadata at {path}")
    return metadata
