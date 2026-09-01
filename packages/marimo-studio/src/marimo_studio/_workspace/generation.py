"""Identify workspace catalogs and view project incarnations."""

from __future__ import annotations

import hashlib
import stat
from collections.abc import Mapping
from pathlib import Path

from marimo_studio._filesystem.io import read_bytes
from marimo_studio._filesystem.paths import validate_portable_path_component
from marimo_studio._filesystem.secure import secure_directory
from marimo_studio._workspace.models import (
    RESERVED_VIEW_NAMES,
    VIEW_NAME_MAX_BYTES,
    VIEW_PATTERN,
    StudioDefinition,
)
from marimo_studio._workspace.project_manifest import VIEW_MANIFEST
from marimo_studio._workspace.view_owners import (
    VIEW_OWNER_DIRECTORY,
    ensure_present_view_owner,
    view_owner_snapshot,
)
from marimo_studio.errors import ConfigurationError
from marimo_studio.view_providers import ViewProject


def _digest(value: object) -> str:
    return hashlib.sha256(repr(value).encode("utf-8")).hexdigest()


def directory_generation(path: Path) -> str:
    """Return an opaque identity for one directory incarnation."""
    with secure_directory(path.parent) as filesystem:
        owner = filesystem.directory_owner(path)
    return _digest(owner)


def view_generation(project: ViewProject) -> str:
    """Return the current incarnation of one named view project."""
    return view_name_generation(project.root.parent, project.name)


def view_name_generation(view_root: Path, name: str) -> str:
    """Return one name's durable owner bound to its current directory."""
    owner, _identity = view_owner_snapshot(view_root, name)
    if owner is None or not owner.present:
        raise FileNotFoundError(view_root / name)
    return _digest(
        (
            owner.generation,
            directory_generation(view_root / name),
        )
    )


def workspace_catalog_generation(
    studio: StudioDefinition,
    views: Mapping[str, ViewProject],
    generations: Mapping[str, str],
    root_generation: str,
) -> str:
    """Return one generation for the configuration and named project catalog."""
    return _digest(
        (
            studio.config_generation,
            root_generation,
            tuple((name, generations[name]) for name in sorted(views)),
        )
    )


def provider_free_catalog_generation(studio: StudioDefinition) -> str:
    """Return a catalog owner while one or more manifests need repair."""
    records: list[tuple[str, str, str, str | None]] = []
    for entry in sorted(studio.view_root.iterdir(), key=lambda path: path.name):
        if entry.name in {".locks", VIEW_OWNER_DIRECTORY}:
            continue
        state = entry.lstat()
        kind = (
            "directory"
            if stat.S_ISDIR(state.st_mode)
            else "file"
            if stat.S_ISREG(state.st_mode)
            else "symlink"
            if stat.S_ISLNK(state.st_mode)
            else "other"
        )
        owner = (
            _provider_free_view_owner(studio, entry)
            if kind == "directory"
            else _digest(
                (
                    state.st_dev,
                    state.st_ino,
                    state.st_mode,
                    state.st_size,
                )
            )
        )
        manifest_digest: str | None = None
        manifest = entry / VIEW_MANIFEST
        if kind == "directory" and manifest.is_file() and not manifest.is_symlink():
            manifest_digest = hashlib.sha256(
                read_bytes(manifest, root=entry),
            ).hexdigest()
        records.append((entry.name, kind, owner, manifest_digest))
    return _digest(
        (
            studio.config_generation,
            directory_generation(studio.view_root),
            tuple(records),
        )
    )


def _provider_free_view_owner(studio: StudioDefinition, entry: Path) -> str:
    manifest = entry / VIEW_MANIFEST
    if manifest.is_file() and not manifest.is_symlink():
        try:
            validate_portable_path_component(
                entry.name,
                field="View name",
                max_bytes=VIEW_NAME_MAX_BYTES,
            )
        except ValueError:
            pass
        else:
            if (
                VIEW_PATTERN.fullmatch(entry.name) is not None
                and entry.name not in RESERVED_VIEW_NAMES
            ):
                try:
                    ensure_present_view_owner(studio.view_root, entry.name)
                except ConfigurationError:
                    pass
                else:
                    return view_name_generation(studio.view_root, entry.name)
    return directory_generation(entry)
