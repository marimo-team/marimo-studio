"""Own reusable provider inspection caches outside view projects."""

from __future__ import annotations

import hashlib
import logging
import os
import stat
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock

from platformdirs import user_cache_path

from marimo_studio._filesystem._entry import is_link
from marimo_studio.errors import ConfigurationError

CACHE_DIR_ENV = "MARIMO_STUDIO_CACHE_DIR"
_LOGGER = logging.getLogger("marimo.studio")


def _private_directory(path: Path) -> None:
    try:
        path.mkdir(mode=0o700, exist_ok=True)
        state = path.lstat()
    except OSError as error:
        raise ConfigurationError(
            f"Could not create the provider inspection cache {path}: "
            f"{error.strerror or type(error).__name__}"
        ) from error
    if is_link(state) or not stat.S_ISDIR(state.st_mode):
        raise ConfigurationError(
            f"Provider inspection cache must be a regular directory: {path}"
        )
    if os.name == "posix" and (
        state.st_uid != os.getuid() or stat.S_IMODE(state.st_mode) & 0o077
    ):
        raise ConfigurationError(
            f"Provider inspection cache must be private to its owner: {path}"
        )


def _persistent_root(cache: Path, namespace: str) -> Path:
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise ConfigurationError(
            f"Could not create the user cache directory {cache.parent}: "
            f"{error.strerror or type(error).__name__}"
        ) from error
    root = cache
    for part in ("inspection", namespace):
        _private_directory(root)
        root /= part
    _private_directory(root)
    return root.resolve()


class _ProcessCache:
    """Hold inspection caches for this process when no persistent one exists."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._directory: TemporaryDirectory[str] | None = None

    def root(self, namespace: str, reason: ConfigurationError) -> Path:
        with self._lock:
            if self._directory is None:
                _LOGGER.warning(
                    "%s Provider inspection uses a temporary cache, so each "
                    "process downloads its dependencies again. Set %s to a "
                    "writable directory to keep them.",
                    reason,
                    CACHE_DIR_ENV,
                )
                self._directory = TemporaryDirectory(prefix="marimo-studio-inspection-")
            return Path(self._directory.name).resolve() / namespace


_PROCESS_CACHE = _ProcessCache()


def inspection_cache_root(provider: str) -> Path:
    """Return a private cache namespace for a provider.

    The namespace persists across processes in ``MARIMO_STUDIO_CACHE_DIR`` or
    the user cache directory. When the user cache directory is unusable,
    inspection keeps a temporary cache for the current process.
    """
    # Deno nests npm packages deeply beneath the cache, so a short namespace
    # keeps their paths under the 260-character Windows limit.
    namespace = hashlib.sha256(provider.encode("utf-8")).hexdigest()[:16]
    configured = os.environ.get(CACHE_DIR_ENV, "")
    if configured:
        if not Path(configured).is_absolute():
            raise ConfigurationError(
                f"{CACHE_DIR_ENV} must be an absolute path, received {configured!r}"
            )
        return _persistent_root(Path(configured), namespace)
    try:
        return _persistent_root(
            user_cache_path("marimo-studio", appauthor=False), namespace
        )
    except ConfigurationError as error:
        return _PROCESS_CACHE.root(namespace, error)
