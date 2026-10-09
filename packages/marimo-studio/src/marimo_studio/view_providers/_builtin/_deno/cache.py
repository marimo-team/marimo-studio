"""Create Deno cache directories without following mutable symlinks."""

from __future__ import annotations

import os
import stat
from contextlib import suppress
from pathlib import Path, PurePosixPath

from marimo_studio.view_providers import project_path


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


_DIRECTORY_FLAGS = (
    os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
)


def _open_resolved(path: Path) -> int:
    """Open a resolved directory one component at a time without following links.

    The cache root lies inside a view project that other local processes can
    change, so a component replaced by a symlink after resolution fails here.
    """
    descriptor = os.open(path.anchor, _DIRECTORY_FLAGS)
    try:
        for part in path.parts[1:]:
            next_descriptor = os.open(part, _DIRECTORY_FLAGS, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def _ensure_descendant_with_descriptors(
    cache_root: Path,
    relative: PurePosixPath,
) -> Path:
    current = cache_root.parent
    try:
        descriptor = _open_resolved(current)
    except OSError as error:
        raise ValueError(
            f"Provider cache path must contain regular directories: {current}"
        ) from error
    try:
        for part in (cache_root.name, *relative.parts):
            with suppress(FileExistsError):
                os.mkdir(part, dir_fd=descriptor)
            mode = os.stat(part, dir_fd=descriptor, follow_symlinks=False).st_mode
            if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
                raise ValueError(
                    f"Provider cache path must be a regular directory: {current / part}"
                )
            next_descriptor = os.open(part, _DIRECTORY_FLAGS, dir_fd=descriptor)
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
    descendant = project_path(relative, field="Provider cache descendant")
    if (
        hasattr(os, "O_DIRECTORY")
        and hasattr(os, "O_NOFOLLOW")
        and os.open in os.supports_dir_fd
        and os.mkdir in os.supports_dir_fd
        and os.stat in os.supports_dir_fd
        and os.stat in os.supports_follow_symlinks
    ):
        return _ensure_descendant_with_descriptors(cache_root, descendant)
    _ensure_directory(cache_root)
    current = cache_root
    for part in descendant.parts:
        current /= part
        _ensure_directory(current)
    return current
