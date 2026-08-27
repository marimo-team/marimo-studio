"""Shared fixtures for source producer and coordinator lifecycle tests."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from marimo_studio._server.development import source_changes
from marimo_studio._server.development.coordinator import SourcePoll, SourceSubscription
from marimo_studio.view_providers._host import provider_registry


async def next_source(subscription: SourceSubscription) -> SourcePoll:
    for _ in range(2_000):
        event = await subscription.poll()
        if event is not None:
            return event
        await asyncio.sleep(0.001)
    raise AssertionError("Shared source monitor did not publish an event")


class CountingProvider:
    def __init__(self, provider: Any) -> None:
        self._provider = provider
        self.inspections = 0

    def inspect(self, request: Any) -> Any:
        self.inspections += 1
        return self._provider.inspect(request)

    def provenance(self, inspection: Any) -> Any:
        return self._provider.provenance(inspection)


def counting_registry(
    monkeypatch: pytest.MonkeyPatch,
    provider_id: str,
) -> CountingProvider:
    provider = CountingProvider(provider_registry().get(provider_id))
    registry = SimpleNamespace(
        get=lambda selected: provider if selected == provider_id else None,
        validate_project=lambda project: project,
    )
    monkeypatch.setattr(source_changes, "provider_registry", lambda: registry)
    return provider
