"""Own reusable provider inspection caches outside view projects."""

from __future__ import annotations

import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock


class _InspectionCacheOwner:
    """Keep inspection caches reusable for this process and dispose them at exit."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._directory: TemporaryDirectory[str] | None = None

    def root(self, provider: str) -> Path:
        with self._lock:
            if self._directory is None:
                self._directory = TemporaryDirectory(prefix="marimo-studio-inspection-")
            root = Path(self._directory.name).resolve()
        namespace = hashlib.sha256(provider.encode("utf-8")).hexdigest()
        return root / namespace


_OWNER = _InspectionCacheOwner()


def inspection_cache_root(provider: str) -> Path:
    """Return one process-owned cache namespace for a provider."""
    return _OWNER.root(provider)
