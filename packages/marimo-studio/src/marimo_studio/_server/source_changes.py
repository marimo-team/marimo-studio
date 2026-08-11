"""Track authored source changes for one Studio event stream."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from marimo_studio._workspace.metadata import notebook_config
from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio._workspace.sources import read_source
from marimo_studio.errors import ConfigurationError, MarimoStudioError

_WatchKey = tuple[str, Path]
_FileStamp = str | tuple[int, int, int, int]


@dataclass(frozen=True)
class SourceChange:
    kind: str
    files: tuple[dict[str, object], ...]


class SourceChangeProducer:
    """Return the next source change relative to a captured baseline."""

    def __init__(self, studio: StudioWorkspace, view_name: str | None) -> None:
        self._studio = studio
        self._view_name = view_name
        self._stamps = _file_stamps(studio)

    def poll(self) -> SourceChange | None:
        current = _file_stamps(self._studio)
        changed = {
            path for path, stamp in current.items() if self._stamps.get(path) != stamp
        } | set(self._stamps).difference(current)
        self._stamps = current
        if not changed:
            return None
        return SourceChange(
            kind=_event_kind(self._studio, changed, self._view_name),
            files=tuple(_changed_files(self._studio, changed, self._view_name)),
        )


def _files(studio: StudioWorkspace) -> tuple[_WatchKey, ...]:
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


def _file_stamps(studio: StudioWorkspace) -> dict[_WatchKey, _FileStamp]:
    result: dict[_WatchKey, _FileStamp] = {}
    for kind, path in _files(studio):
        try:
            if kind == "config" and studio.uses_notebook_config:
                config = notebook_config(path)
                result[(kind, path)] = hashlib.sha256(
                    repr(config).encode("utf-8")
                ).hexdigest()
            elif os.name == "nt":
                result[(kind, path)] = hashlib.sha256(path.read_bytes()).hexdigest()
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
    studio: StudioWorkspace,
    changed: set[_WatchKey],
    view_name: str | None,
) -> str:
    if view_name is None:
        return "views"
    if not (studio.view_root / view_name).is_dir():
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


def _changed_files(
    studio: StudioWorkspace,
    changed: set[_WatchKey],
    view_name: str | None,
) -> list[dict[str, object]]:
    if view_name is None:
        return []
    root = (studio.view_root / view_name).resolve()
    files: list[dict[str, object]] = []
    for kind, path in sorted(changed, key=lambda item: str(item[1])):
        if kind != "view":
            continue
        try:
            relative = path.resolve().relative_to(root)
        except ValueError:
            continue
        source_name = relative.as_posix()
        try:
            revision = f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"
        except OSError:
            try:
                revision = read_source(studio, view_name, source_name).revision
            except (MarimoStudioError, OSError):
                revision = None
        files.append({"path": source_name, "revision": revision})
    return files


__all__ = ["SourceChange", "SourceChangeProducer"]
