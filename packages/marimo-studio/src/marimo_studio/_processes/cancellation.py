"""Propagate cancellation from async owners into provider threads."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from marimo_studio.view_providers import ProviderCancellation


class _ProviderCancellationFacade(ProviderCancellation):
    """Expose provider cancellation through its core lifecycle owner."""

    def __init__(self, owner: ProviderOperationControl) -> None:
        super().__init__()
        self._owner = owner

    @property
    def cancelled(self) -> bool:
        return self._owner.cancelled

    def cancel(self) -> None:
        self._owner.cancel()

    def register(self, callback: Callable[[], None]) -> Callable[[], None]:
        return self._owner.register(callback)


class ProviderOperationControl:
    """Own provider cancellation and the final commit that competes with it."""

    def __init__(self) -> None:
        self._signal = ProviderCancellation()
        self._lock = threading.Lock()
        self.cancellation = _ProviderCancellationFacade(self)

    @property
    def cancelled(self) -> bool:
        return self._signal.cancelled

    def cancel(self) -> None:
        with self._lock:
            self._signal.cancel()

    def register(self, callback: Callable[[], None]) -> Callable[[], None]:
        return self._signal.register(callback)

    def commit_if_active(self, commit: Callable[[], None]) -> bool:
        """Run one final commit when it wins the race with cancellation."""
        with self._lock:
            if self._signal.cancelled:
                return False
            commit()
            return True


_CURRENT_PROVIDER_CANCELLATION: ContextVar[ProviderCancellation | None] = ContextVar(
    "marimo_studio_provider_cancellation",
    default=None,
)
_CURRENT_PROVIDER_OPERATION: ContextVar[ProviderOperationControl | None] = ContextVar(
    "marimo_studio_provider_operation",
    default=None,
)


def current_provider_cancellation() -> ProviderCancellation | None:
    """Return the cancellation owner installed for this provider call."""
    return _CURRENT_PROVIDER_CANCELLATION.get()


def current_provider_operation() -> ProviderOperationControl | None:
    """Return the core lifecycle owner installed for this provider call."""
    return _CURRENT_PROVIDER_OPERATION.get()


@contextmanager
def provider_cancellation(
    control: ProviderOperationControl | ProviderCancellation,
) -> Iterator[None]:
    """Install one cancellation owner for a synchronous provider operation."""
    if isinstance(control, ProviderOperationControl):
        operation = control
        cancellation = control.cancellation
    else:
        operation = None
        cancellation = control
    cancellation_token = _CURRENT_PROVIDER_CANCELLATION.set(cancellation)
    operation_token = _CURRENT_PROVIDER_OPERATION.set(operation)
    try:
        yield
    finally:
        _CURRENT_PROVIDER_OPERATION.reset(operation_token)
        _CURRENT_PROVIDER_CANCELLATION.reset(cancellation_token)
