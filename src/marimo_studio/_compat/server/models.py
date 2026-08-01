"""Shared state read from a running Marimo server."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

ServerMode = Literal["edit", "run"]


@dataclass(frozen=True)
class ServerLocation:
    notebook: Path
    file_key: str
    base_url: str
    mode: ServerMode
    _state: Any
    _session_manager: Any


@dataclass(frozen=True)
class ServerContext:
    notebook: Path
    file_key: str
    base_url: str
    mode: ServerMode
    dev: bool
    user_config: dict[str, Any]
    config_overrides: dict[str, Any]
    server_token: str
    _server: Any
    _session_manager: Any
