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


def _files(studio: StudioConfig) -> tuple[Path, ...]:
    try:
        view_files = tuple(
            path for path in studio.view_root.rglob("*") if path.is_file()
        )
    except OSError:
        view_files = ()
    return (studio.config_path, *view_files)


def _file_stamps(studio: StudioConfig) -> dict[Path, int | str]:
    result: dict[Path, int | str] = {}
    for path in _files(studio):
        try:
            if studio.uses_notebook_config and path == studio.config_path:
                config = notebook_config(path)
                result[path] = hashlib.sha256(repr(config).encode("utf-8")).hexdigest()
            else:
                result[path] = path.stat().st_mtime_ns
        except (OSError, ConfigurationError):
            continue
    return result


def _event_kind(
    studio: StudioConfig,
    changed: set[Path],
    view_name: str | None,
) -> str:
    if view_name is None:
        return "views"
    if studio.config_path in changed:
        return "html"
    view_root = (studio.view_root / view_name).resolve()
    selected = []
    for path in changed:
        try:
            path.resolve().relative_to(view_root)
        except ValueError:
            continue
        selected.append(path)
    if not selected:
        return "views"
    return "css" if all(path.suffix == ".css" for path in selected) else "html"


async def change_events(
    studio: StudioConfig,
    view_name: str | None = None,
) -> AsyncIterator[bytes]:
    """Yield change events until the requesting client disconnects."""
    stamps = _file_stamps(studio)
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
