"""Stream filesystem changes to Studio and active view previews."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import AsyncIterator
from pathlib import Path

from marimo_studio._workspace.metadata import notebook_config
from marimo_studio._workspace.models import StudioConfig
from marimo_studio.errors import ConfigurationError

_WatchKey = tuple[str, Path]
_FileStamp = str | tuple[int, int, int, int]


def _files(studio: StudioConfig) -> tuple[_WatchKey, ...]:
    try:
        view_files = tuple(
            path for path in studio.view_root.rglob("*") if path.is_file()
        )
    except OSError:
        view_files = ()
    return (
        ("config", studio.config_path),
        ("notebook", studio.notebook),
        *(("view", path) for path in view_files),
    )


def _file_stamps(studio: StudioConfig) -> dict[_WatchKey, _FileStamp]:
    result: dict[_WatchKey, _FileStamp] = {}
    for kind, path in _files(studio):
        try:
            if kind == "config" and studio.uses_notebook_config:
                config = notebook_config(path)
                result[(kind, path)] = hashlib.sha256(
                    repr(config).encode("utf-8")
                ).hexdigest()
            else:
                stat = path.stat()
                result[(kind, path)] = (
                    stat.st_mtime_ns,
                    stat.st_ctime_ns,
                    stat.st_size,
                    stat.st_ino,
                )
        except (OSError, ConfigurationError):
            continue
    return result


def _event_kind(
    studio: StudioConfig,
    changed: set[_WatchKey],
    view_name: str | None,
) -> str:
    if view_name is None:
        return "views"
    if any(kind == "config" for kind, _ in changed):
        return "html"
    view_root = (studio.view_root / view_name).resolve()
    selected: list[Path] = []
    for kind, path in changed:
        if kind != "view":
            continue
        try:
            path.resolve().relative_to(view_root)
        except ValueError:
            continue
        selected.append(path)
    if selected:
        selected_css = all(path.suffix == ".css" for path in selected)
        notebook_changed = any(kind == "notebook" for kind, _ in changed)
        return "css" if selected_css and not notebook_changed else "html"
    if any(kind == "notebook" for kind, _ in changed):
        return "runtime"
    return "views"


async def change_events(
    studio: StudioConfig,
    view_name: str | None = None,
) -> AsyncIterator[bytes]:
    """Yield change events until the requesting client disconnects."""
    stamps = _file_stamps(studio)
    yield b"event: ready\ndata: {}\n\n"
    last_heartbeat = time.monotonic()
    while True:
        await asyncio.sleep(0.25)
        current = _file_stamps(studio)
        changed = {
            path for path, stamp in current.items() if stamps.get(path) != stamp
        } | set(stamps).difference(current)
        stamps = current
        if not changed:
            now = time.monotonic()
            if now - last_heartbeat >= 15:
                last_heartbeat = now
                yield b": keepalive\n\n"
            continue
        last_heartbeat = time.monotonic()
        payload = json.dumps(
            {"kind": _event_kind(studio, changed, view_name)},
            separators=(",", ":"),
        )
        yield f"event: change\ndata: {payload}\n\n".encode()
