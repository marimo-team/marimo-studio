"""Own keyed browser compilation for the latest request from each owner."""

from __future__ import annotations

import hashlib
import os
from functools import partial
from pathlib import Path

from marimo_studio._delivery.browser_ports import (
    BrowserRuntimeProjection,
    BrowserRuntimeProjector,
)
from marimo_studio._processes.latest_work import LatestWork
from marimo_studio.errors._internal import RuntimeSyncError

_ProjectionKey = tuple[str, str, str, str]
_OwnerKey = tuple[str, str]


class WasmProjectionWork:
    """Coalesce one browser build key and retain each owner's latest request."""

    def __init__(self, projector: BrowserRuntimeProjector) -> None:
        self._projector = projector
        self._latest = LatestWork[BrowserRuntimeProjection](
            superseded_error=lambda: RuntimeSyncError(
                "A newer browser runtime revision replaced this request."
            ),
            closed_error=lambda: RuntimeSyncError(
                "Browser runtime projection is shutting down."
            ),
        )

    async def project(
        self,
        notebook: Path,
        source: str,
        owner: _OwnerKey,
    ) -> BrowserRuntimeProjection:
        return await self._latest.run(
            self._key(notebook, source),
            owner,
            partial(self._projector.project, notebook, source),
        )

    async def close(self) -> None:
        await self._latest.close()

    def _key(self, notebook: Path, source: str) -> _ProjectionKey:
        return (
            os.path.normcase(os.path.abspath(notebook)),
            hashlib.sha256(source.encode("utf-8")).hexdigest(),
            self._projector.version,
            self._projector.commit,
        )
