"""Report file operations that a contained tree refuses or cannot complete."""

from __future__ import annotations

from pathlib import Path

from marimo_studio.errors import ConfigurationError


class UnsafePathError(ConfigurationError, OSError):
    """Report a path outside its root, through a link, or of the wrong kind."""


class ConcurrentChangeError(ConfigurationError, OSError):
    """Report a file that changed while Studio read or verified it."""

    transient = True


class FileAccessError(ConfigurationError, OSError):
    """Report a file that the operating system refused to read or write."""


class FileTooLargeError(ConfigurationError, OSError):
    """Report a file larger than the caller's read bound."""

    def __init__(self, path: Path, size: int, limit: int) -> None:
        super().__init__(f"{path} is {size} bytes. The limit is {limit} bytes.")
        self.path = path
        self.size = size
        self.limit = limit
