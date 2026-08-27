"""Provider-facing cancellation and supervised command contracts."""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class ProviderCancellation:
    """Share one cancellation request across a provider operation."""

    def __init__(self) -> None:
        self._cancelled = threading.Event()
        self._lock = threading.Lock()
        self._callbacks: dict[object, Callable[[], None]] = {}

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    def cancel(self) -> None:
        with self._lock:
            if self._cancelled.is_set():
                return
            self._cancelled.set()
            callbacks = tuple(self._callbacks.values())
            self._callbacks.clear()
        for callback in callbacks:
            self._dispatch(callback)

    def register(self, callback: Callable[[], None]) -> Callable[[], None]:
        if not callable(callback):
            raise TypeError("Provider cancellation callback must be callable")
        token = object()
        with self._lock:
            cancelled = self._cancelled.is_set()
            if not cancelled:
                self._callbacks[token] = callback
        if cancelled:
            self._dispatch(callback)

        def unregister() -> None:
            with self._lock:
                self._callbacks.pop(token, None)

        return unregister

    @staticmethod
    def _dispatch(callback: Callable[[], None]) -> None:
        def invoke() -> None:
            try:
                callback()
            except BaseException:
                return

        threading.Thread(
            target=invoke,
            name="marimo-studio-provider-cancel",
            daemon=True,
        ).start()


@dataclass(frozen=True)
class ProviderCommandResult:
    """Return bounded text output from one supervised provider command."""

    returncode: int
    stdout: str
    stderr: str


class ProviderRunner(Protocol):
    """Run child commands inside one view snapshot with cancellation."""

    def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        timeout: float = 120.0,
        environment: Mapping[str, str] | None = None,
    ) -> ProviderCommandResult: ...
