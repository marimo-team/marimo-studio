"""Stable records shared by server ports and services."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, NewType

ServerMode = Literal["edit", "run"]
ServerHandle = NewType("ServerHandle", object)


@dataclass(frozen=True)
class ServerLocation:
    notebook: Path
    file_key: str
    base_url: str
    mode: ServerMode
    routing_query: tuple[tuple[str, str], ...]
    handle: ServerHandle = field(repr=False)
    internal_url: str | None = None


@dataclass(frozen=True)
class ServerContext:
    notebook: Path
    file_key: str
    base_url: str
    mode: ServerMode
    dev: bool
    routing_query: tuple[tuple[str, str], ...]
    user_config: dict[str, object]
    config_overrides: dict[str, object]
    server_token: str
    handle: ServerHandle = field(repr=False)
    internal_url: str | None = None


@dataclass(frozen=True)
class SaveCell:
    code: str
    runtime_id: str


@dataclass(frozen=True)
class SourceTransformResult:
    source: str
    commit: Callable[[], None] = lambda: None
