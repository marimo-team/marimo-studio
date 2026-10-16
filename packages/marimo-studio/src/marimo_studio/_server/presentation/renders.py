"""Own render workers, shared render jobs, and rendered bundles.

Renders run on two owned worker threads. Requests for the same render of the
same artifact revision with the same inputs share one job. Once every request
waiting on a job has left, queued work never starts, and running work continues
for a short grace period and then stops. A page cancels its render whenever the
notebook's results change, so a new request with unchanged inputs continues the
job instead of starting over.
Each finished render becomes an immutable bundle on disk, stored once by
content.

A reader's session holds the bundle it currently shows for each render, so
media requests and downloads keep working while other readers render. The
store evicts the least recently used bundles beyond its byte budget, skipping
bundles that a live session holds.
"""

from __future__ import annotations

import asyncio
import secrets
import shutil
import tempfile
import threading
from collections import OrderedDict
from collections.abc import Callable, Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import suppress
from dataclasses import dataclass, field, replace
from functools import partial
from pathlib import Path, PurePosixPath

from marimo_studio._server.presentation.service import (
    NotebookPresentation,
    PresentationSnapshot,
)
from marimo_studio._views.renders import (
    RenderBundle,
    canonical_values,
    render_key,
    run_render,
)
from marimo_studio.errors import ConfigurationError, MarimoStudioError
from marimo_studio.errors._internal import ArtifactIntegrityError
from marimo_studio.view_providers import (
    JsonValue,
    ProviderCancellation,
    Representation,
)
from marimo_studio.view_providers._host import provider_registry

_STORE_MAX_BYTES = 2 * 1024 * 1024 * 1024
# Input sets remembered for their bundles. Many input sets can render
# identical files, so this bounds the map apart from the byte budget.
_RESULTS_KEPT = 4_096
# Verified templates kept on disk, one per recently rendered artifact revision.
_TEMPLATES_KEPT = 8
_RENDER_WORKERS = 2
# Covers the page's request delay and a prompt capture of unchanged inputs.
_ABANDONED_GRACE_SECONDS = 1.0

# (view, artifact revision, render key)
_JobKey = tuple[str, str, bytes]
# (session ID, view, render source)
_HoldKey = tuple[str, str, PurePosixPath]


class RenderUnavailable(Exception):
    """The presentation revision or the render owner stopped before rendering."""


@dataclass
class _Job:
    work: Future[RenderBundle]
    task: asyncio.Future[RenderBundle]
    cancellation: ProviderCancellation
    waiters: int = 0
    # Stops the job once its grace period ends without a new request.
    abandoned: asyncio.TimerHandle | None = None


@dataclass
class _Stored:
    bundle: RenderBundle
    views: set[str] = field(default_factory=set)


class RenderStore:
    """Own render workers, shared render jobs, and rendered bundles."""

    def __init__(
        self,
        *,
        max_bytes: int = _STORE_MAX_BYTES,
        abandoned_grace: float = _ABANDONED_GRACE_SECONDS,
    ) -> None:
        self._lock = threading.Lock()
        self._abandoned_grace = abandoned_grace
        self._directory: Path | None = None
        self._max_bytes = max_bytes
        self._bytes = 0
        self._bundles: OrderedDict[str, _Stored] = OrderedDict()
        # Identical files from different inputs share one bundle, and each
        # input set keeps its own warnings.
        self._results: OrderedDict[_JobKey, RenderBundle] = OrderedDict()
        self._holds: dict[_HoldKey, str] = {}
        self._jobs: dict[_JobKey, _Job] = {}
        # Each template is verified once per artifact revision, and renders
        # copy it from here. A template in use by a render is never removed.
        self._templates: OrderedDict[tuple[str, str], Path] = OrderedDict()
        self._template_users: dict[Path, int] = {}
        self._executor = ThreadPoolExecutor(
            max_workers=_RENDER_WORKERS,
            thread_name_prefix="marimo-studio-render",
        )
        self._closed = False

    async def render(
        self,
        presentation: NotebookPresentation,
        snapshot: PresentationSnapshot,
        source: PurePosixPath,
        values: Mapping[str, object],
        outputs: Mapping[str, Representation],
        cells: Mapping[str, Representation],
        *,
        holder: str | None,
        alive: Callable[[str], bool],
    ) -> RenderBundle:
        """Return the bundle that renders ``source`` with these inputs, once.

        ``holder`` names the reader's session, which then holds the bundle until
        it adopts another one for the same render or ends. ``alive`` reports
        whether a holding session still exists.
        """

        def keyed() -> tuple[dict[str, JsonValue], bytes]:
            normalized, encoded = canonical_values(values)
            return normalized, render_key(source, encoded, outputs, cells)

        # Encoding megabytes of values and hashing output bytes stays off the
        # event loop.
        normalized, digest = await asyncio.to_thread(keyed)
        view = snapshot.view_name
        key: _JobKey = (view, snapshot.artifact.artifact_revision, digest)
        with self._lock:
            if self._closed:
                raise RenderUnavailable("Rendering has stopped")
            result = self._results.get(key)
            if result is not None and result.id in self._bundles:
                self._results.move_to_end(key)
                self._bundles.move_to_end(result.id)
                self._hold_locked(holder, view, source, result.id)
                return result
            job = self._jobs.get(key)
            if job is None:
                work = self._executor.submit(
                    self._render,
                    key,
                    presentation,
                    snapshot,
                    source,
                    normalized,
                    outputs,
                    cells,
                    cancellation := ProviderCancellation(),
                )
                job = _Job(work, asyncio.wrap_future(work), cancellation)
                job.task.add_done_callback(partial(self._settled, key, job))
                self._jobs[key] = job
            job.waiters += 1
            if job.abandoned is not None:
                job.abandoned.cancel()
                job.abandoned = None
        try:
            bundle = await asyncio.shield(job.task)
        except asyncio.CancelledError:
            # Closing the store cancels queued work, which the reader sees as a
            # transient result. Otherwise this request was cancelled, and the
            # job stops after its grace period once no request waits on it.
            if job.task.cancelled():
                raise RenderUnavailable("Rendering has stopped") from None
            with self._lock:
                job.waiters -= 1
                # Queued work never starts, and running work continues for
                # its grace period.
                if job.waiters == 0 and not job.work.cancel():
                    job.abandoned = asyncio.get_running_loop().call_later(
                        self._abandoned_grace, self._stop_abandoned, key, job
                    )
            raise
        except BaseException:
            with self._lock:
                job.waiters -= 1
            raise
        with self._lock:
            job.waiters -= 1
            self._hold_locked(holder, view, source, bundle.id)
            evicted = self._evict_locked(alive, keep=bundle.id)
        if evicted:
            await asyncio.to_thread(_remove, evicted)
        return bundle

    def _stop_abandoned(self, key: _JobKey, job: _Job) -> None:
        """Stop the provider work of a job no request rejoined in its grace."""
        with self._lock:
            if job.waiters > 0:
                return
            job.abandoned = None
            if self._jobs.get(key) is job:
                del self._jobs[key]
        job.cancellation.cancel()

    def _settled(
        self, key: _JobKey, job: _Job, task: asyncio.Future[RenderBundle]
    ) -> None:
        """Retire a finished job. Its bundle stays in the results."""
        if not task.cancelled():
            # A job that no request awaits ends without an unread error.
            task.exception()
        with self._lock:
            if job.abandoned is not None:
                job.abandoned.cancel()
                job.abandoned = None
            if self._jobs.get(key) is job:
                del self._jobs[key]

    def file(
        self,
        view: str,
        bundle_id: str,
        path: PurePosixPath,
    ) -> tuple[Path, str, str] | None:
        """Return the disk path, media type, and digest of one rendered file.

        A bundle answers only for the views that rendered it.
        """
        with self._lock:
            stored = self._bundles.get(bundle_id)
            if stored is None or view not in stored.views:
                return None
            self._bundles.move_to_end(bundle_id)
            item = stored.bundle.file(path)
            if item is None:
                return None
            return (
                stored.bundle.root.joinpath(*item.path.parts),
                item.media_type,
                item.sha256,
            )

    def _hold_locked(
        self, holder: str | None, view: str, source: PurePosixPath, bundle_id: str
    ) -> None:
        if holder is not None:
            self._holds[holder, view, source] = bundle_id

    def _root_locked(self) -> Path:
        if self._directory is None:
            self._directory = Path(tempfile.mkdtemp(prefix="marimo-studio-renders-"))
        return self._directory

    def _render(
        self,
        key: _JobKey,
        presentation: NotebookPresentation,
        snapshot: PresentationSnapshot,
        source: PurePosixPath,
        values: dict[str, JsonValue],
        outputs: Mapping[str, Representation],
        cells: Mapping[str, Representation],
        cancellation: ProviderCancellation,
    ) -> RenderBundle:
        if cancellation.cancelled:
            raise RenderUnavailable("The render request ended")
        artifact = snapshot.artifact

        with self._lock:
            if self._closed:
                raise RenderUnavailable("Rendering has stopped")
            pending = self._root_locked() / f".pending-{secrets.token_hex(16)}"
        templates: list[Path] = []

        def copy_template(destination: Path) -> None:
            templates.append(self._checkout_template(presentation, snapshot))
            shutil.copytree(templates[0], destination, copy_function=shutil.copyfile)

        try:
            bundle = run_render(
                provider_registry().get(artifact.provider.key),
                copy_template,
                source,
                values,
                outputs,
                cells,
                cancellation,
                pending,
            )
        except MarimoStudioError as error:
            if cancellation.cancelled:
                raise RenderUnavailable("The render request ended") from error
            raise
        finally:
            for template in templates:
                self._return_template(template)
        stored = self._remember(key, bundle, cancelled=cancellation.cancelled)
        if stored is None:
            raise RenderUnavailable("The render request ended")
        return stored

    def _checkout_template(
        self,
        presentation: NotebookPresentation,
        snapshot: PresentationSnapshot,
    ) -> Path:
        """Return the verified template of the snapshot's artifact revision.

        The first render of a revision copies the template out of its lease,
        verifying every file, and later renders reuse that copy. Call
        ``_return_template`` once the render has copied it.
        """
        key = (snapshot.view_name, snapshot.artifact.artifact_revision)
        with self._lock:
            if self._closed:
                raise RenderUnavailable("Rendering has stopped")
            template = self._templates.get(key)
            if template is not None:
                self._templates.move_to_end(key)
                self._template_users[template] += 1
                return template
            pending = self._root_locked() / f".template-{secrets.token_hex(16)}"
        lease = presentation.lease_artifact(*key)
        if lease is None:
            raise RenderUnavailable("The presentation revision was retired")
        with lease:
            try:
                lease.copy_template(pending)
            except ArtifactIntegrityError as error:
                with suppress(OSError, ConfigurationError):
                    lease.record_corruption(error)
                shutil.rmtree(pending, ignore_errors=True)
                raise
        retired: list[Path] = []
        with self._lock:
            template = self._templates.get(key)
            if template is None:
                template = pending
                self._templates[key] = template
                # Counted before retiring, so the new template stays.
                self._template_users[template] = 1
                while len(self._templates) > _TEMPLATES_KEPT:
                    oldest = next(
                        (
                            candidate
                            for candidate, path in self._templates.items()
                            if self._template_users[path] == 0
                        ),
                        None,
                    )
                    if oldest is None:
                        break
                    path = self._templates.pop(oldest)
                    del self._template_users[path]
                    retired.append(path)
            else:
                retired.append(pending)
                self._template_users[template] += 1
        _remove(retired)
        return template

    def _return_template(self, template: Path) -> None:
        with self._lock:
            if template in self._template_users:
                self._template_users[template] -= 1

    def _remember(
        self,
        key: _JobKey,
        bundle: RenderBundle,
        *,
        cancelled: bool,
    ) -> RenderBundle | None:
        """Store a finished bundle once by content, or discard it.

        A render can finish after close() or after every request left, and
        then its files are discarded.
        """
        discard = bundle.root
        result = None
        with self._lock:
            if self._closed or cancelled:
                stored = None
            else:
                stored = self._bundles.get(bundle.id)
                if stored is None:
                    root = self._root_locked() / bundle.id
                    bundle.root.rename(root)
                    discard = None
                    stored = _Stored(replace(bundle, root=root, warnings=()))
                    self._bundles[bundle.id] = stored
                    self._bytes += bundle.size
                stored.views.add(key[0])
                result = replace(stored.bundle, warnings=bundle.warnings)
                self._results[key] = result
                self._results.move_to_end(key)
                while len(self._results) > _RESULTS_KEPT:
                    self._results.popitem(last=False)
        if discard is not None:
            shutil.rmtree(discard, ignore_errors=True)
        return result

    def _evict_locked(self, alive: Callable[[str], bool], *, keep: str) -> list[Path]:
        """Detach least recently used bundles that no live session holds.

        Each evicted bundle moves aside under the lock, so a render of identical
        files stores a fresh copy while the old one is removed.
        """
        # Holds of ended sessions go first, so holds stay bounded by live
        # sessions even while the store stays under its budget.
        for hold in [hold for hold in self._holds if not alive(hold[0])]:
            del self._holds[hold]
        if self._bytes <= self._max_bytes:
            return []
        held = set(self._holds.values())
        evicted: list[Path] = []
        for bundle_id in list(self._bundles):
            if self._bytes <= self._max_bytes:
                break
            if bundle_id == keep or bundle_id in held:
                continue
            stored = self._bundles.pop(bundle_id)
            self._bytes -= stored.bundle.size
            aside = stored.bundle.root.with_name(f".evicted-{secrets.token_hex(16)}")
            stored.bundle.root.rename(aside)
            evicted.append(aside)
        if evicted:
            self._results = OrderedDict(
                (key, result)
                for key, result in self._results.items()
                if result.id in self._bundles
            )
        return evicted

    def close(self) -> None:
        """Cancel active renders, wait for their workers, and remove every bundle."""
        with self._lock:
            self._closed = True
            active = tuple(job.cancellation for job in self._jobs.values())
            self._bundles.clear()
            self._results.clear()
            self._holds.clear()
            self._bytes = 0
            directory = self._directory
        for cancellation in active:
            cancellation.cancel()
        self._executor.shutdown(wait=True, cancel_futures=True)
        if directory is not None:
            shutil.rmtree(directory, ignore_errors=True)


def _remove(roots: list[Path]) -> None:
    for root in roots:
        shutil.rmtree(root, ignore_errors=True)
