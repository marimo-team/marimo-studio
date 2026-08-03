"""Locate the packaged browser runtime and read its Marimo version."""

from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path

from marimo_studio.errors import ProtocolError


def runtime_assets_path() -> Path:
    return Path(str(files("marimo_studio").joinpath("_static", "server-runtime")))


def runtime_marimo_version() -> str:
    path = runtime_assets_path() / "build-meta.json"
    try:
        version = json.loads(path.read_text(encoding="utf-8"))["marimo"]["version"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise ProtocolError(
            f"Invalid browser runtime metadata at {path}: {error}"
        ) from error
    if not isinstance(version, str) or not version:
        raise ProtocolError(f"Invalid browser runtime metadata at {path}")
    return version
