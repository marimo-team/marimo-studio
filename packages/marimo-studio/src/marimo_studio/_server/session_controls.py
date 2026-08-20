"""Inspect live session controls independently of prepared publications."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import cast

import marimo_export.sessions as marimo_export_sessions
from marimo_export.wire import portable_json

from marimo_studio._capabilities import ServerContext
from marimo_studio.errors import RuntimeSyncError

_CACHE_LIMIT = 8


class SessionControlBindingReader:
    """Read semantic control paths from one validated live session."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._cache: OrderedDict[
            tuple[Path, str, str, int], Mapping[str, Mapping[str, object]]
        ] = OrderedDict()

    async def bindings(
        self,
        context: ServerContext,
        session_id: str,
        notebook_revision: str,
        control_revision: int,
    ) -> Mapping[str, Mapping[str, object]]:
        internal_url = context.internal_url
        if internal_url is None:
            raise RuntimeSyncError(
                "Studio is waiting for the local server endpoint to become available."
            )
        key = (context.notebook, session_id, notebook_revision, control_revision)
        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
            return cached
        async with self._lock:
            cached = self._cache.get(key)
            if cached is not None:
                self._cache.move_to_end(key)
                return cached
            try:
                bindings = await asyncio.to_thread(
                    _inspect_bindings,
                    internal_url,
                    context.server_token,
                    session_id,
                )
            except Exception as error:
                raise RuntimeSyncError(
                    "Studio is waiting for live control metadata."
                ) from error
            self._cache[key] = bindings
            self._cache.move_to_end(key)
            while len(self._cache) > _CACHE_LIMIT:
                self._cache.popitem(last=False)
            return bindings


def _inspect_bindings(
    server: str,
    server_token: str,
    session_id: str,
) -> Mapping[str, Mapping[str, object]]:
    with marimo_export_sessions.Client(server, server_token=server_token) as client:
        observation = client.session(session_id).observe_inputs()
    values = {
        object_id: binding.to_value()
        for object_id, binding in observation.control_bindings.items()
    }
    return cast(
        Mapping[str, Mapping[str, object]],
        _freeze_json(portable_json(values, "runtime control bindings")),
    )


def _freeze_json(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze_json(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    return value


__all__ = ["SessionControlBindingReader"]
