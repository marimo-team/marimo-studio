"""File watching contracts consumed by development services."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

FileChangeCallback = Callable[[Path], Awaitable[None]]


@dataclass(frozen=True)
class ProjectWatchPlan:
    files: tuple[Path, ...]
    roots: tuple[Path, ...]
    excluded: tuple[Path, ...] = ()


class ProjectWatcher(Protocol):
    async def replace(
        self,
        plan: ProjectWatchPlan,
        callback: FileChangeCallback,
    ) -> None: ...

    async def close(self) -> None: ...


class ProjectWatcherFactory(Protocol):
    def __call__(self) -> ProjectWatcher: ...
