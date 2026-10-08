"""Own document render workers, active renders, and cached renditions.

Renders run on two owned worker threads, and identical values for one artifact
revision share a cached rendition. A render's cancellation stops its provider
commands, and closing the owner cancels every active render.
"""

from __future__ import annotations

import asyncio
import threading
from collections import OrderedDict
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from pathlib import Path

from marimo_studio._server.presentation.service import (
    NotebookPresentation,
    PresentationSnapshot,
)
from marimo_studio._views.documents import (
    Rendition,
    canonical_values,
    render_document,
    render_key,
)
from marimo_studio.errors import ConfigurationError, MarimoStudioError
from marimo_studio.errors._internal import ArtifactIntegrityError
from marimo_studio.view_providers import (
    JsonValue,
    ProviderCancellation,
    Representation,
)
from marimo_studio.view_providers._host import provider_registry

_CACHE_MAX_BYTES = 64 * 1024 * 1024
_RENDER_WORKERS = 2


class RenderUnavailable(Exception):
    """The presentation revision or the render owner stopped before rendering."""


class DocumentRenders:
    """Own document render workers, active renders, and cached renditions."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cache: OrderedDict[tuple[str, bytes], Rendition] = OrderedDict()
        self._cache_bytes = 0
        self._active: set[ProviderCancellation] = set()
        self._executor = ThreadPoolExecutor(
            max_workers=_RENDER_WORKERS,
            thread_name_prefix="marimo-studio-render",
        )
        self._closed = False

    async def render(
        self,
        presentation: NotebookPresentation,
        snapshot: PresentationSnapshot,
        values: Mapping[str, object],
        outputs: Mapping[str, Representation],
        cells: Mapping[str, Representation],
    ) -> Rendition:
        normalized, encoded = canonical_values(values)
        key = (
            snapshot.artifact.artifact_revision,
            render_key(encoded, outputs, cells),
        )
        cancellation = ProviderCancellation()
        with self._lock:
            if self._closed:
                raise RenderUnavailable("Document rendering has stopped")
            cached = self._cache.get(key)
            if cached is not None:
                self._cache.move_to_end(key)
                return cached
            self._active.add(cancellation)
            work = asyncio.get_running_loop().run_in_executor(
                self._executor,
                self._render,
                key,
                presentation,
                snapshot,
                normalized,
                outputs,
                cells,
                cancellation,
            )
        try:
            rendition = await asyncio.shield(work)
        except asyncio.CancelledError:
            cancellation.cancel()
            await asyncio.wait({work})
            raise
        finally:
            with self._lock:
                self._active.discard(cancellation)
        return rendition

    def _render(
        self,
        key: tuple[str, bytes],
        presentation: NotebookPresentation,
        snapshot: PresentationSnapshot,
        values: dict[str, JsonValue],
        outputs: Mapping[str, Representation],
        cells: Mapping[str, Representation],
        cancellation: ProviderCancellation,
    ) -> Rendition:
        if cancellation.cancelled:
            raise RenderUnavailable("The render request ended")
        # Identical requests can queue behind the workers. The worker stores
        # each rendition before it takes the next request, so queued requests
        # reuse it.
        with self._lock:
            cached = self._cache.get(key)
        if cached is not None:
            return cached
        artifact = snapshot.artifact
        template = artifact.template
        assert template is not None

        def copy_template(destination: Path) -> None:
            lease = presentation.lease_artifact(
                snapshot.view_name,
                artifact.artifact_revision,
            )
            if lease is None:
                raise RenderUnavailable("The presentation revision was retired")
            with lease:
                try:
                    lease.copy_template(destination)
                except ArtifactIntegrityError as error:
                    with suppress(OSError, ConfigurationError):
                        lease.record_corruption(error)
                    raise

        try:
            rendition = render_document(
                provider_registry().get(artifact.provider.key),
                copy_template,
                template.document,
                values,
                outputs,
                cells,
                cancellation,
            )
        except MarimoStudioError as error:
            if cancellation.cancelled:
                raise RenderUnavailable("The render request ended") from error
            raise
        self._remember(key, rendition)
        return rendition

    def _remember(self, key: tuple[str, bytes], rendition: Rendition) -> None:
        size = len(rendition.content)
        if size > _CACHE_MAX_BYTES:
            return
        with self._lock:
            if self._closed or key in self._cache:
                return
            self._cache[key] = rendition
            self._cache_bytes += size
            while self._cache_bytes > _CACHE_MAX_BYTES:
                _key, evicted = self._cache.popitem(last=False)
                self._cache_bytes -= len(evicted.content)

    def close(self) -> None:
        """Cancel active renders, wait for their workers, and drop the cache."""
        with self._lock:
            self._closed = True
            active = tuple(self._active)
            self._cache.clear()
            self._cache_bytes = 0
        for cancellation in active:
            cancellation.cancel()
        self._executor.shutdown(wait=True, cancel_futures=True)
