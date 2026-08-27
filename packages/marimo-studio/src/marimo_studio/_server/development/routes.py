"""Adapt source and agent lifecycle events to Studio's SSE protocol."""

from __future__ import annotations

import asyncio
import json
import time
from collections import deque
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from functools import partial
from itertools import count
from typing import TypeVar

from marimo_studio._processes.ownership import (
    propagate_cancellation,
    settle_ownership,
)
from marimo_studio._processes.provider_operation import (
    find_process_cleanup_error,
    process_cleanup_errors,
    raise_process_cleanup,
    run_provider_operation,
)
from marimo_studio._processes.supervisor import ProcessCleanupError
from marimo_studio._server.agent.clients import StudioClientRegistry
from marimo_studio._server.agent.coordinator import AgentCoordinator
from marimo_studio._server.development.client_events import (
    WorkspaceClientEventProducer,
)
from marimo_studio._server.development.coordinator import (
    DevelopmentCoordinator,
    SourceSubscription,
)
from marimo_studio._server.development.source_changes import (
    SourceChange,
    SourceChangeProducer,
)
from marimo_studio._views.presentation_publication import (
    publish_presentation as _publish_presentation,
)
from marimo_studio._views.revisions import (
    PreparedViewProject,
    capture_published_presentations,
)
from marimo_studio._workspace.models import StudioWorkspace
from marimo_studio.errors import MarimoStudioError

_T = TypeVar("_T")
_EVENT_POLL_INTERVAL = 0.05
_STOP_POLL_INTERVAL = 0.25
_HEARTBEAT_INTERVAL = 15.0
_CONTROL_EVENT_LIMIT = 32


@dataclass(frozen=True)
class _ProducerFailure:
    error: Exception


@dataclass(frozen=True)
class _PresentationRequest:
    generation: int
    previous_revision: str | None = None


@dataclass(frozen=True)
class _CoalescedEvent:
    generation: int
    sequence: int
    event: bytes


class DevelopmentStreamCleanupError(RuntimeError):
    """Report stream release failures after every owner was attempted."""

    def __init__(self, errors: tuple[Exception, ...]) -> None:
        self.errors = errors
        super().__init__(
            "Development stream cleanup failed: "
            + "; ".join(str(error) for error in errors)
        )


async def _close_stream_owners(
    source: SourceSubscription | None,
    browser: WorkspaceClientEventProducer | None,
) -> tuple[tuple[Exception, ...], asyncio.CancelledError | None]:
    errors: list[Exception] = []
    cancellation: asyncio.CancelledError | None = None
    for owner in (browser, source):
        if owner is None:
            continue
        try:
            _result, current = await settle_ownership(owner.close())
        except asyncio.CancelledError as error:
            current = error
        except Exception as error:
            errors.append(error)
            continue
        if cancellation is None and current is not None:
            cancellation = current
    return tuple(errors), cancellation


async def _finish_stream(
    tasks: tuple[asyncio.Task[None], ...],
    source: SourceSubscription | None,
    browser: WorkspaceClientEventProducer | None,
    broker: _EventBroker | None = None,
) -> tuple[tuple[Exception, ...], asyncio.CancelledError | None]:
    """Release stream identity before draining cancelled producers."""
    for task in tasks:
        task.cancel()
    errors, cancellation = await _close_stream_owners(source, browser)
    if tasks:
        results = await asyncio.gather(*tasks, return_exceptions=True)
        errors = (
            *errors,
            *(
                result
                for result in results
                if isinstance(result, Exception)
                and not isinstance(result, asyncio.CancelledError)
                and (broker is None or not broker.observed_failure(result))
            ),
        )
    return errors, cancellation


def _propagate_stream_cleanup(
    errors: tuple[Exception, ...],
    owner_cancellation: asyncio.CancelledError | None,
    cancellation: asyncio.CancelledError | None,
) -> None:
    if errors:
        error = DevelopmentStreamCleanupError(errors)
        deferred = cancellation or owner_cancellation
        if deferred is not None:
            raise error from deferred
        raise error
    propagate_cancellation(cancellation or owner_cancellation)


class _EventBroker:
    """Retain lossless control and coalesced development state."""

    def __init__(self, *, control_limit: int = _CONTROL_EVENT_LIMIT) -> None:
        if control_limit < 1:
            raise ValueError("Control event limit must be positive")
        self._condition = asyncio.Condition()
        self._control: deque[bytes | _ProducerFailure] = deque()
        self._control_limit = control_limit
        self._source: dict[tuple[str, str], _CoalescedEvent] = {}
        self._publication: dict[tuple[str, str], _CoalescedEvent] = {}
        self._heartbeat: bytes | None = None
        self._sequence = count()
        self._observed_failures: set[int] = set()
        self.last_activity = time.monotonic()

    @property
    def retained_events(self) -> int:
        return (
            len(self._control)
            + len(self._source)
            + len(self._publication)
            + (self._heartbeat is not None)
        )

    async def emit_control(
        self,
        event: bytes | _ProducerFailure,
    ) -> None:
        async with self._condition:
            await self._condition.wait_for(
                lambda: len(self._control) < self._control_limit
            )
            self.last_activity = time.monotonic()
            self._control.append(event)
            self._condition.notify_all()

    async def fail(self, error: Exception) -> None:
        await self.emit_control(_ProducerFailure(error))

    async def emit_source(
        self,
        view: str,
        kind: str,
        generation: int,
        event: bytes,
        resync: bytes,
    ) -> None:
        async with self._condition:
            key = (view, kind)
            current = self._source.get(key)
            if current is not None and current.generation > generation:
                return
            selected = resync if current is not None else event
            self._source[key] = _CoalescedEvent(
                generation,
                next(self._sequence),
                selected,
            )
            self.last_activity = time.monotonic()
            self._condition.notify_all()

    async def emit_publication(
        self,
        view: str,
        kind: str,
        generation: int,
        event: bytes,
    ) -> None:
        async with self._condition:
            key = (view, kind)
            current = self._publication.get(key)
            if current is not None and current.generation > generation:
                return
            self._publication[key] = _CoalescedEvent(
                generation,
                next(self._sequence),
                event,
            )
            self.last_activity = time.monotonic()
            self._condition.notify_all()

    async def emit_heartbeat(self, event: bytes) -> None:
        async with self._condition:
            self._heartbeat = event
            self.last_activity = time.monotonic()
            self._condition.notify_all()

    async def receive(self) -> bytes | _ProducerFailure:
        async with self._condition:
            await self._condition.wait_for(lambda: self.retained_events > 0)
            if self._control:
                event = self._control.popleft()
                if isinstance(event, _ProducerFailure):
                    self._observed_failures.add(id(event.error))
                self._condition.notify_all()
                return event
            if self._source:
                key = min(self._source, key=lambda item: self._source[item].sequence)
                return self._source.pop(key).event
            if self._publication:
                key = min(
                    self._publication,
                    key=lambda item: self._publication[item].sequence,
                )
                return self._publication.pop(key).event
            assert self._heartbeat is not None
            event = self._heartbeat
            self._heartbeat = None
            return event

    def observed_failure(self, error: Exception) -> bool:
        return id(error) in self._observed_failures


def _encode(kind: str, payload: dict[str, object]) -> bytes:
    body = json.dumps(payload, separators=(",", ":"))
    return f"event: {kind}\ndata: {body}\n\n".encode()


async def change_events(
    studio: StudioWorkspace | None,
    view_name: str | None = None,
    stop_requested: Callable[[], bool] | None = None,
    clients: StudioClientRegistry | None = None,
    agents: AgentCoordinator | None = None,
    client_id: str | None = None,
    stream_generation: int | None = None,
    active_view: str | None = None,
    development: DevelopmentCoordinator | None = None,
) -> AsyncGenerator[bytes, None]:
    """Yield source and agent events until the client disconnects."""
    should_stop = stop_requested or (lambda: False)
    selected_view = view_name or active_view
    browser = _browser_events(
        view_name,
        clients,
        agents,
        client_id,
        stream_generation,
        active_view,
    )
    source_subscription: SourceSubscription | None = None
    sources: SourceChangeProducer | None = None
    broker: _EventBroker | None = None
    tasks: list[asyncio.Task[None]] = []
    try:
        if browser is not None and not await browser.reserve():
            return
        source_subscription = (
            await development.subscribe(studio, selected_view)
            if studio is not None and development is not None
            else None
        )
        sources = (
            await asyncio.to_thread(SourceChangeProducer, studio, selected_view)
            if studio is not None and source_subscription is None
            else None
        )
        baseline_operation = (
            partial(_presentation_baseline, studio, selected_view)
            if studio is not None
            else None
        )
        baseline: dict[str, object]
        if (
            baseline_operation is not None
            and development is not None
            and source_subscription is not None
            and selected_view is not None
        ):
            baseline = await development.baseline(
                selected_view,
                source_subscription.generation,
                baseline_operation,
            )
        elif baseline_operation is not None:
            baseline = await _publish_async(baseline_operation)
        else:
            baseline = {}

        broker = _EventBroker()
        if browser is not None:
            if not await browser.connect():
                return
            tasks.append(
                _start_producer(
                    lambda: _produce_browser_events(browser, should_stop, broker),
                    broker,
                )
            )
        yield _encode("ready", baseline)

        presentation_requests: asyncio.Queue[_PresentationRequest] = asyncio.Queue(
            maxsize=1
        )
        initial_presentation_ready = asyncio.Event()
        if studio is not None and selected_view is not None:
            baseline_revision = baseline.get("revision")
            _request_presentation(
                presentation_requests,
                _PresentationRequest(
                    generation=(
                        source_subscription.generation
                        if source_subscription is not None
                        else 0
                    ),
                    previous_revision=(
                        baseline_revision
                        if isinstance(baseline_revision, str)
                        else None
                    ),
                ),
            )
            tasks.append(
                _start_producer(
                    lambda: _produce_publication_events(
                        studio,
                        selected_view,
                        development,
                        presentation_requests,
                        initial_presentation_ready,
                        broker,
                    ),
                    broker,
                )
            )
            if development is not None and view_name is None:
                tasks.append(
                    _start_producer(
                        lambda: _prepare_presentations_after_initial(
                            studio,
                            selected_view,
                            development,
                            initial_presentation_ready,
                        ),
                        broker,
                    )
                )
        if source_subscription is not None or sources is not None:
            tasks.append(
                _start_producer(
                    lambda: _produce_source_events(
                        source_subscription,
                        sources,
                        studio,
                        selected_view,
                        presentation_requests,
                        should_stop,
                        broker,
                    ),
                    broker,
                )
            )
        tasks.append(
            _start_producer(
                lambda: _produce_heartbeats(should_stop, broker),
                broker,
            )
        )

        while not should_stop():
            try:
                event = await asyncio.wait_for(
                    broker.receive(),
                    timeout=_STOP_POLL_INTERVAL,
                )
            except TimeoutError:
                continue
            if isinstance(event, _ProducerFailure):
                raise event.error
            yield event
    finally:
        (cleanup_errors, owner_cancellation), cancellation = await settle_ownership(
            _finish_stream(tuple(tasks), source_subscription, browser, broker)
        )
        _propagate_stream_cleanup(
            cleanup_errors,
            owner_cancellation,
            cancellation,
        )


def _start_producer(
    producer: Callable[[], Awaitable[None]],
    broker: _EventBroker,
) -> asyncio.Task[None]:
    async def run() -> None:
        try:
            await producer()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            cleanup = find_process_cleanup_error(error)
            try:
                await broker.fail(error)
            except asyncio.CancelledError as cancellation:
                if cleanup is not None:
                    raise cleanup from cancellation
                raise
            raise_process_cleanup(error)
            task = asyncio.current_task()
            if task is not None and task.cancelling():
                raise

    return asyncio.create_task(run())


async def _produce_browser_events(
    browser: WorkspaceClientEventProducer,
    should_stop: Callable[[], bool],
    broker: _EventBroker,
) -> None:
    while not should_stop():
        for event in await browser.poll():
            await broker.emit_control(_encode(event.kind, event.payload))
        await asyncio.sleep(_EVENT_POLL_INTERVAL)


async def _produce_source_events(
    source_subscription: SourceSubscription | None,
    sources: SourceChangeProducer | None,
    studio: StudioWorkspace | None,
    selected_view: str | None,
    presentation_requests: asyncio.Queue[_PresentationRequest],
    should_stop: Callable[[], bool],
    broker: _EventBroker,
) -> None:
    local_generation = 0
    while not should_stop():
        await asyncio.sleep(_EVENT_POLL_INTERVAL)
        source_poll = (
            await source_subscription.poll()
            if source_subscription is not None
            else None
        )
        change = source_poll.change if source_poll is not None else None
        generation = source_poll.generation if source_poll is not None else 0
        if sources is not None:
            change = await asyncio.to_thread(sources.poll)
            if change is not None:
                local_generation += 1
                generation = local_generation
        if change is None:
            continue
        if change.kind == "resync":
            views_event = _encode(
                "change",
                {
                    "schema": 1,
                    "kind": "views",
                    "files": [],
                },
            )
            await broker.emit_source(
                selected_view or "",
                "views",
                generation,
                views_event,
                views_event,
            )
            change = SourceChange(kind="project", files=())
        event = _encode(
            "change",
            {
                "schema": 1,
                "kind": change.kind,
                "files": list(change.files),
                **({"error": change.error} if change.error is not None else {}),
            },
        )
        resync = _encode(
            "change",
            {
                "schema": 1,
                "kind": change.kind,
                "files": [],
                **({"error": change.error} if change.error is not None else {}),
            },
        )
        await broker.emit_source(
            selected_view or "",
            change.kind,
            generation,
            event,
            resync,
        )
        if (
            change.kind in {"project", "views"}
            and studio is not None
            and selected_view is not None
        ):
            _request_presentation(
                presentation_requests,
                _PresentationRequest(generation),
            )


def _request_presentation(
    requests: asyncio.Queue[_PresentationRequest],
    request: _PresentationRequest,
) -> None:
    if requests.full():
        pending = requests.get_nowait()
        if pending.generation > request.generation:
            request = pending
    requests.put_nowait(request)


async def _produce_publication_events(
    studio: StudioWorkspace,
    selected_view: str,
    development: DevelopmentCoordinator | None,
    requests: asyncio.Queue[_PresentationRequest],
    initial_ready: asyncio.Event,
    broker: _EventBroker,
) -> None:
    first = True
    while True:
        request = await requests.get()
        async for kind, event in _presentation_events(
            studio,
            selected_view,
            request.generation,
            development,
            previous_revision=request.previous_revision,
        ):
            await broker.emit_publication(
                selected_view,
                kind,
                request.generation,
                event,
            )
        if first:
            first = False
            initial_ready.set()


async def _prepare_presentations_after_initial(
    studio: StudioWorkspace,
    selected_view: str,
    development: DevelopmentCoordinator,
    initial_ready: asyncio.Event,
) -> None:
    await initial_ready.wait()
    await _prepare_inactive_presentations(studio, selected_view, development)


async def _produce_heartbeats(
    should_stop: Callable[[], bool],
    broker: _EventBroker,
) -> None:
    while not should_stop():
        await asyncio.sleep(1)
        if time.monotonic() - broker.last_activity >= _HEARTBEAT_INTERVAL:
            await broker.emit_heartbeat(b": keepalive\n\n")


async def _presentation_events(
    studio: StudioWorkspace,
    view_name: str,
    generation: int,
    development: DevelopmentCoordinator | None,
    *,
    previous_revision: str | None = None,
) -> AsyncIterator[tuple[str, bytes]]:
    yield (
        "build",
        _encode(
            "change",
            {
                "schema": 1,
                "kind": "build",
                "view": view_name,
                "phase": "building",
                "files": [],
            },
        ),
    )
    build, revision, artifact_revision = await _prepare_presentation(
        studio,
        view_name,
        generation,
        development,
    )
    yield (
        "build",
        _encode(
            "change",
            {
                "schema": 1,
                "kind": "build",
                "view": view_name,
                "build": build,
                "revision": revision,
                "files": [],
            },
        ),
    )
    if revision is not None and revision != previous_revision:
        yield (
            "presentation",
            _encode(
                "change",
                {
                    "schema": 1,
                    "kind": "presentation",
                    "view": view_name,
                    "revision": revision,
                    "artifact_revision": artifact_revision,
                    "files": [],
                },
            ),
        )


async def _prepare_presentation(
    studio: StudioWorkspace,
    view_name: str,
    generation: int | None,
    development: DevelopmentCoordinator | None,
    *,
    warmup: bool = False,
) -> tuple[dict[str, object], str | None, str | None]:
    prepared: PreparedViewProject | None = None
    if development is not None:
        try:
            catalog = await development.project_catalog(studio, view_name)
        except (MarimoStudioError, OSError) as error:
            raise_process_cleanup(error)
            return await development.publish(
                view_name,
                0 if generation is None else generation,
                partial(_publish_presentation, studio, view_name),
                warmup=warmup,
            )
        prepared = PreparedViewProject(catalog.inspection, catalog.input_id)
        generation = catalog.generation if generation is None else generation
    operation = partial(_publish_presentation, studio, view_name, prepared)
    if development is not None:
        assert generation is not None
        return await development.publish(
            view_name,
            generation,
            operation,
            warmup=warmup,
        )
    return await _publish_async(operation)


async def _prepare_inactive_presentations(
    studio: StudioWorkspace,
    selected_view: str,
    development: DevelopmentCoordinator,
) -> None:
    async def prepare(view_name: str) -> None:
        try:
            await _prepare_presentation(
                studio,
                view_name,
                None,
                development,
                warmup=True,
            )
        except asyncio.CancelledError:
            raise
        except ProcessCleanupError:
            raise
        except (MarimoStudioError, OSError) as error:
            raise_process_cleanup(error)
            return

    tasks = [
        asyncio.create_task(prepare(view_name))
        for view_name in studio.views
        if view_name != selected_view
    ]
    try:
        await asyncio.gather(*tasks)
    except BaseException as failure:
        for task in tasks:
            task.cancel()
        results, _cancellation = await settle_ownership(
            asyncio.gather(*tasks, return_exceptions=True)
        )
        cleanup = process_cleanup_errors(results)
        if cleanup:
            raise cleanup[0] from failure
        raise


async def _publish_async(
    operation: Callable[[], _T],
) -> _T:
    return await run_provider_operation(operation)


def _presentation_baseline(
    studio: StudioWorkspace,
    view_name: str | None,
) -> dict[str, object]:
    if view_name is None:
        return {}
    try:
        snapshot = capture_published_presentations(studio, (view_name,))
        if snapshot is None:
            revision = None
        else:
            with snapshot as captured:
                revision = captured.revision(view_name)
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
    stream_generation: int | None,
    active_view: str | None,
) -> WorkspaceClientEventProducer | None:
    if (
        view_name is not None
        or clients is None
        or agents is None
        or client_id is None
        or stream_generation is None
    ):
        return None
    return WorkspaceClientEventProducer(
        clients,
        agents,
        client_id,
        stream_generation,
        active_view,
    )
