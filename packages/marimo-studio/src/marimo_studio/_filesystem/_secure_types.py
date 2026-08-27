"""Shared records for contained filesystem operations."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path


class SecureFileError(OSError):
    """Report a contained path that cannot be operated on safely."""


class ConditionalWriteError(SecureFileError):
    """Report a failed conditional write and any preserved recovery file."""

    def __init__(self, message: str, *, recovery: Path | None = None) -> None:
        super().__init__(message)
        self.recovery = recovery


@dataclass(frozen=True)
class ParentHandle:
    path: Path
    descriptor: int | None


ParentContext = Callable[[Path], AbstractContextManager[ParentHandle]]


@dataclass(frozen=True)
class FileIdentity:
    device: int
    inode: int
    mode: int
    size: int
    digest: bytes
    directory: bool
