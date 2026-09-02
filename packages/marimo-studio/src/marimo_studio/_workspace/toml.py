"""Read bounded Studio TOML documents."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from marimo_studio._filesystem.io import read_text
from marimo_studio.errors import ConfigurationError


def parse_toml(source: str, path: Path) -> dict[str, Any]:
    """Parse one TOML source with its owning path in diagnostics."""
    try:
        return tomllib.loads(source)
    except tomllib.TOMLDecodeError as error:
        raise ConfigurationError(f"Invalid TOML in {path}: {error}") from error


def read_toml(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise ConfigurationError(f"Configuration is a symlink: {path}")
    return parse_toml(read_text(path, root=path.parent), path)
