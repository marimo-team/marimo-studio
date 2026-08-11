"""Lifecycle primitives for reversible private Marimo patches."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from threading import Lock
from typing import Any

from marimo_studio._capabilities import CloseHandle
from marimo_studio.errors import CompatibilityError


class CallbackCloseHandle:
    """Run one close callback at most once."""

    def __init__(self, callback: Callable[[], None]) -> None:
        self._callback = callback
        self._lock = Lock()
        self._closed = False

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._callback()
            self._closed = True


class CompositeCloseHandle:
    """Close owned handles in reverse installation order."""

    def __init__(self, handles: Iterable[CloseHandle]) -> None:
        self._handles = tuple(handles)
        self._lock = Lock()
        self._closed = False

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            failure: BaseException | None = None
            failed: list[CloseHandle] = []
            for handle in reversed(self._handles):
                try:
                    close = handle.close
                    close()
                except BaseException as error:
                    failed.append(handle)
                    if failure is None:
                        failure = error
            self._handles = tuple(reversed(failed))
            self._closed = not self._handles
            if failure is not None:
                raise failure


class ReversiblePatch:
    """Reference-count one class or module attribute replacement."""

    def __init__(
        self,
        capability: str,
        owner: object,
        attribute: str,
        replacement: Callable[[Any], Any],
    ) -> None:
        self.capability = capability
        self._owner = owner
        self._attribute = attribute
        self._factory = replacement
        self._lock = Lock()
        self._users = 0
        self._original: Any | None = None
        self._replacement: Any | None = None

    def open(self) -> CallbackCloseHandle:
        with self._lock:
            current = getattr(self._owner, self._attribute)
            if self._users:
                if current is not self._replacement:
                    raise CompatibilityError(
                        f"Another owner replaced {self.capability!r} while Studio "
                        "was using it."
                    )
            else:
                self._original = current
                self._replacement = self._factory(current)
                setattr(self._owner, self._attribute, self._replacement)
            self._users += 1
        return CallbackCloseHandle(self._release)

    def _release(self) -> None:
        with self._lock:
            if self._users <= 0:
                raise RuntimeError(f"Unbalanced patch release for {self.capability}")
            if self._users > 1:
                self._users -= 1
                return
            current = getattr(self._owner, self._attribute)
            if current is not self._replacement:
                raise CompatibilityError(
                    f"Another owner replaced {self.capability!r} before Studio "
                    "could restore it."
                )
            setattr(self._owner, self._attribute, self._original)
            self._users = 0
            self._original = None
            self._replacement = None


__all__ = ["CallbackCloseHandle", "CompositeCloseHandle", "ReversiblePatch"]
