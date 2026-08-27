"""Create Deno cache directories without following mutable symlinks."""

from __future__ import annotations

import os
import stat
from contextlib import suppress
from pathlib import Path, PurePosixPath

from marimo_studio._artifacts.paths import ensure_secure_directory
from marimo_studio.errors import ConfigurationError
from marimo_studio.view_providers._validation import validate_relative_path


def _validate_directory(path: Path) -> None:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError as error:
        raise ValueError(f"Provider cache directory is missing: {path}") from error
    if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
        raise ValueError(f"Provider cache path must be a regular directory: {path}")


def _ensure_directory(path: Path) -> None:
    with suppress(FileExistsError):
        os.mkdir(path)
    _validate_directory(path)


def _ensure_descendant_with_descriptors(
    cache_root: Path,
    relative: PurePosixPath,
) -> Path:
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptor = os.open(cache_root, flags)
    current = cache_root
    try:
        for part in relative.parts:
            with suppress(FileExistsError):
                os.mkdir(part, dir_fd=descriptor)
            mode = os.stat(part, dir_fd=descriptor, follow_symlinks=False).st_mode
            if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
                raise ValueError(
                    f"Provider cache path must be a regular directory: {current / part}"
                )
            next_descriptor = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
            current /= part
        return current
    except OSError as error:
        raise ValueError(
            f"Provider cache path must contain regular directories: {current}"
        ) from error
    finally:
        os.close(descriptor)


def ensure_cache_directory(cache_root: Path, relative: PurePosixPath) -> Path:
    """Create one Deno cache descendant through non-following paths."""
    if not isinstance(cache_root, Path) or not cache_root.is_absolute():
        raise ValueError("Provider cache root must be an absolute path")
    try:
        mode = cache_root.lstat().st_mode
    except FileNotFoundError:
        pass
    else:
        if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
            raise ValueError(
                f"Provider cache path must be a regular directory: {cache_root}"
            )
    if cache_root.resolve() != cache_root:
        raise ValueError("Provider cache root must be resolved")
    descendant = validate_relative_path(relative, field="Provider cache descendant")
    if cache_root.name == ".cache" and cache_root.parent.name == ".artifacts":
        try:
            ensure_secure_directory(
                cache_root.parent.parent,
                cache_root,
                "provider cache",
            )
        except ConfigurationError as error:
            raise ValueError(str(error)) from error
    else:
        _ensure_directory(cache_root)
    if (
        hasattr(os, "O_DIRECTORY")
        and hasattr(os, "O_NOFOLLOW")
        and os.open in os.supports_dir_fd
        and os.mkdir in os.supports_dir_fd
        and os.stat in os.supports_dir_fd
        and os.stat in os.supports_follow_symlinks
    ):
        return _ensure_descendant_with_descriptors(cache_root, descendant)
    current = cache_root
    for part in descendant.parts:
        current /= part
        _ensure_directory(current)
    return current
