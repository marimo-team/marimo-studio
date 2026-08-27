"""Publish Marimo session snapshots without exposing partial cache files.

Marimo uses its session cache to restore notebook sessions. Studio wraps the
pinned cache writer for one server lifetime so each changed snapshot replaces
the previous JSON file atomically. Readers see either the previous complete
snapshot or the new complete snapshot.

An in-flight threaded write settles before cancellation is propagated. The
original Marimo writer is restored when the owning application closes.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from marimo._session.state import serialize as native_session_cache
from marimo._session.state.serialize import SessionCacheWriter
from marimo._utils.async_path import AsyncPath

from marimo_studio._compat.patch import CallbackCloseHandle, ReversiblePatch
from marimo_studio._filesystem.io import atomic_write_text


def _run_replacement(_native_run: Any) -> Any:
    async def run(writer: SessionCacheWriter) -> None:
        while writer.running:
            try:
                if writer.session_view.needs_export("session"):
                    writer.session_view.mark_auto_export_session()
                    native_session_cache.LOGGER.debug(
                        f"Writing session view to cache {writer.path}"
                    )
                    data = native_session_cache.serialize_session_view(
                        writer.session_view,
                        cell_ids=writer.document.cell_ids,
                        script_metadata_hash=(
                            native_session_cache._script_metadata_hash(
                                writer.notebook_path
                            )
                        ),
                        drop_virtual_file_outputs=True,
                    )
                    content = json.dumps(data, indent=2)
                    path = Path(writer.path)
                    if isinstance(writer.path, AsyncPath):
                        await asyncio.to_thread(atomic_write_text, path, content)
                    else:
                        atomic_write_text(path, content)
                await asyncio.sleep(writer.interval)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                native_session_cache.LOGGER.error(f"Write error: {error}")
                break

    return run


_RUN_PATCH = ReversiblePatch(
    "session-cache-publication",
    SessionCacheWriter,
    "run",
    _run_replacement,
)


class PrivateSessionCachePublication:
    """Own atomic session-cache publication for one server lifespan."""

    def open(self) -> CallbackCloseHandle:
        return _RUN_PATCH.open()
