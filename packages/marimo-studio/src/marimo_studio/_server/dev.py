"""Adapt source and agent lifecycle events to Studio's SSE protocol."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Callable

from marimo_studio._server.agent_coordinator import AgentCoordinator
from marimo_studio._server.live_clients import StudioClientRegistry
from marimo_studio._server.source_changes import SourceChangeProducer
from marimo_studio._server.workspace_client_events import (
    WorkspaceClientEventProducer,
)
from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio._workspace.revisions import capture_studio_sources
from marimo_studio.errors import MarimoStudioError


def _encode(kind: str, payload: dict[str, object]) -> bytes:
    body = json.dumps(payload, separators=(",", ":"))
    return f"event: {kind}\ndata: {body}\n\n".encode()


async def change_events(
    studio: StudioWorkspace,
    view_name: str | None = None,
    stop_requested: Callable[[], bool] | None = None,
    clients: StudioClientRegistry | None = None,
    agents: AgentCoordinator | None = None,
    client_id: str | None = None,
    active_view: str | None = None,
) -> AsyncIterator[bytes]:
    """Yield source and agent events until the client disconnects."""
    should_stop = stop_requested or (lambda: False)
    selected_view = view_name or active_view
    sources = SourceChangeProducer(studio, selected_view)
    browser = _browser_events(
        view_name,
        clients,
        agents,
        client_id,
        active_view,
    )
    if browser is not None:
        await browser.connect()
    try:
        baseline = await asyncio.to_thread(_source_baseline, studio, selected_view)
        yield _encode("ready", baseline)
        last_heartbeat = time.monotonic()
        while not should_stop():
            await asyncio.sleep(0.25)
            if should_stop():
                return
            if browser is not None:
                for event in await browser.poll():
                    yield _encode(event.kind, event.payload)
            change = sources.poll()
            if change is not None:
                last_heartbeat = time.monotonic()
                yield _encode(
                    "change",
                    {
                        "schema": 1,
                        "kind": change.kind,
                        "files": list(change.files),
                    },
                )
                continue
            now = time.monotonic()
            if now - last_heartbeat >= 15:
                last_heartbeat = now
                yield b": keepalive\n\n"
    finally:
        if browser is not None:
            await browser.close()


def _source_baseline(
    studio: StudioWorkspace,
    view_name: str | None,
) -> dict[str, object]:
    if view_name is None:
        return {}
    try:
        revision = capture_studio_sources(studio, (view_name,)).revision(view_name)
    except (MarimoStudioError, OSError):
        revision = None
    return {
        "schema": 1,
        "view": view_name,
        "revision": revision,
    }


def _browser_events(
    view_name: str | None,
    clients: StudioClientRegistry | None,
    agents: AgentCoordinator | None,
    client_id: str | None,
    active_view: str | None,
) -> WorkspaceClientEventProducer | None:
    if view_name is not None or clients is None or agents is None or client_id is None:
        return None
    return WorkspaceClientEventProducer(
        clients,
        agents,
        client_id,
        active_view,
    )


__all__ = ["change_events"]
