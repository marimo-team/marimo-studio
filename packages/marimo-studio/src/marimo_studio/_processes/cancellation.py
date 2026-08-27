"""Propagate cancellation from async owners into provider threads."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from marimo_studio.view_providers import ProviderCancellation

_CURRENT_PROVIDER_OPERATION: ContextVar[ProviderCancellation | None] = ContextVar(
    "marimo_studio_provider_cancellation",
    default=None,
)


def current_provider_cancellation() -> ProviderCancellation | None:
    """Return the cancellation owner installed for this provider call."""
    return _CURRENT_PROVIDER_OPERATION.get()


@contextmanager
def provider_cancellation(control: ProviderCancellation) -> Iterator[None]:
    """Install one cancellation owner for a synchronous provider operation."""
    token = _CURRENT_PROVIDER_OPERATION.set(control)
    try:
        yield
    finally:
        _CURRENT_PROVIDER_OPERATION.reset(token)
