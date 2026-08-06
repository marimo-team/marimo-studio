"""Remove named views and keep the configured default valid."""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import MutableMapping
from contextlib import suppress
from pathlib import Path
from typing import Any

import tomlkit

from marimo_studio._workspace.config import (
    editable_studio_config,
    load_studio,
)
from marimo_studio._workspace.files import (
    atomic_write_text,
    read_text,
    reject_mutable_symlinks,
)
from marimo_studio._workspace.metadata import update_notebook_config
from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio.errors import (
    LastViewError,
    ViewDeletionError,
    ViewNotFoundError,
)


def _set_default(studio: StudioWorkspace, name: str) -> None:
    def update(config: MutableMapping[str, Any]) -> None:
        config["default"] = name

    if studio.uses_notebook_config:
        update_notebook_config(studio.notebook, update)
        return

    document = tomlkit.parse(read_text(studio.config_path))
    editable_studio_config(document)["default"] = name
    atomic_write_text(studio.config_path, tomlkit.dumps(document))


def _restore_view(staged: Path, target: Path, staging_root: Path) -> None:
    os.replace(staged, target)
    staging_root.rmdir()


def delete_view(studio: StudioWorkspace, name: str) -> StudioWorkspace:
    """Delete one view directory and return the updated workspace."""
    current = load_studio(studio.config_path)
    if name not in current.views:
        raise ViewNotFoundError(name)
    if len(current.views) == 1:
        raise LastViewError()

    target = current.view_root / name
    reject_mutable_symlinks(
        current.root,
        {current.config_path, current.view_root.parent, target},
    )
    if not target.is_dir() or not (target / "index.html").is_file():
        raise ViewNotFoundError(name)

    remaining = tuple(view for view in current.views if view != name)
    next_default = (
        remaining[0] if current.default_view == name else current.default_view
    )
    staging_root = Path(
        tempfile.mkdtemp(
            dir=current.view_root.parent,
            prefix=f".{current.view_root.name}-{name}-",
        )
    )
    staged = staging_root / name
    try:
        os.replace(target, staged)
        if next_default != current.default_view:
            try:
                _set_default(current, next_default)
            except Exception:
                _restore_view(staged, target, staging_root)
                raise
        try:
            shutil.rmtree(staging_root)
        except OSError as error:
            raise ViewDeletionError() from error
    except Exception:
        if staging_root.exists() and not staged.exists():
            with suppress(OSError):
                staging_root.rmdir()
        raise
    return load_studio(current.config_path)
