"""Adapt programmatic Marimo applications to an outer ASGI mount."""

from __future__ import annotations

import asyncio
import logging
import sys
from collections.abc import AsyncIterator, Callable
from contextlib import (
    AbstractAsyncContextManager,
    AsyncExitStack,
    asynccontextmanager,
)
from pathlib import Path
from threading import Event, Lock, Thread, current_thread
from time import monotonic
from types import ModuleType
from typing import Any, Protocol, cast

from starlette.middleware import Middleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from marimo_studio._compat.server.gateway import (
    config_manager_at_notebook,
    effective_base_url,
)
from marimo_studio._processes.ownership import (
    propagate_cancellation,
    settle_ownership,
)
from marimo_studio._processes.supervisor import ProcessCleanupError
from marimo_studio._server.ports import ServerAdapters
from marimo_studio.errors import ProtocolError

_LifespanContext = Callable[[Any], AbstractAsyncContextManager[Any]]
_AdapterFactory = Callable[[], ServerAdapters]
_KERNEL_JOIN_TIMEOUT = 5.0
_MISSING_MAIN = object()
LOGGER = logging.getLogger(__name__)


class _PresentationApplication(Protocol):
    def lifespan(self) -> AbstractAsyncContextManager[Any]: ...


class _MainModuleOwnership:
    """Restore the host module after the final programmatic kernel exits."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._owners: set[object] = set()
        self._host: ModuleType | object = _MISSING_MAIN
        self._kernel_candidates: set[ModuleType] = set()
        self._pending: dict[object, tuple[Thread, ...]] = {}
        self._terminals: dict[object, Event] = {}
        self._reapers: dict[object, Thread] = {}
        self._deferred_error: BaseException | None = None

    def open(self) -> object:
        token = object()
        with self._lock:
            self._reap_settled_locked()
            if self._deferred_error is not None:
                raise ProcessCleanupError(
                    "Deferred programmatic kernel cleanup failed"
                ) from self._deferred_error
            if self._pending:
                raise ProcessCleanupError(
                    "A programmatic Marimo kernel is still shutting down"
                )
            if not self._owners:
                self._host = sys.modules.get("__main__", _MISSING_MAIN)
                self._kernel_candidates.clear()
            self._owners.add(token)
        return token

    def observe_kernel_module(self, notebook_paths: frozenset[str]) -> None:
        current = sys.modules.get("__main__")
        if not isinstance(current, ModuleType):
            return
        current_file = getattr(current, "__file__", None)
        if not isinstance(current_file, str) or current_file not in notebook_paths:
            return
        with self._lock:
            if self._owners and current is not self._host:
                self._kernel_candidates.add(current)

    def defer(self, token: object, threads: tuple[Thread, ...]) -> Event:
        terminal = Event()
        with self._lock:
            if token not in self._owners:
                terminal.set()
                return terminal
            existing = self._terminals.get(token)
            if existing is not None:
                return existing
            self._pending[token] = threads
            self._terminals[token] = terminal
            if all(not thread.is_alive() for thread in threads):
                self._pending.pop(token, None)
                self._terminals.pop(token, None)
                try:
                    self._release_locked(token)
                finally:
                    terminal.set()
                return terminal
            reaper = Thread(
                target=self._reap,
                args=(token,),
                name="marimo-studio-programmatic-kernel-reaper",
                daemon=True,
            )
            self._reapers[token] = reaper
            try:
                reaper.start()
            except BaseException:
                self._reapers.pop(token, None)
                self._reap_settled_locked()
                raise
        return terminal

    def close(self, token: object) -> None:
        with self._lock:
            self._reap_settled_locked()
            if token in self._pending:
                return
            self._release_locked(token)

    def _reap(self, token: object) -> None:
        with self._lock:
            threads = self._pending.get(token, ())
            terminal = self._terminals.get(token)
        for thread in threads:
            if thread is not current_thread() and thread.ident is not None:
                thread.join()
        error: BaseException | None = None
        try:
            with self._lock:
                if token not in self._pending:
                    return
                self._settle_pending_locked(token)
        except BaseException as deferred_error:
            error = deferred_error
        finally:
            if terminal is not None:
                terminal.set()
        if error is not None:
            LOGGER.error(
                "Deferred programmatic kernel cleanup failed",
                exc_info=(type(error), error, error.__traceback__),
            )

    def _reap_settled_locked(self) -> None:
        settled = tuple(
            token
            for token, threads in self._pending.items()
            if all(not thread.is_alive() for thread in threads)
        )
        for token in settled:
            self._settle_pending_locked(token)

    def _settle_pending_locked(self, token: object) -> None:
        terminal = self._terminals.pop(token, None)
        self._pending.pop(token, None)
        self._reapers.pop(token, None)
        try:
            self._release_locked(token)
        except BaseException as error:
            self._deferred_error = error
            raise
        finally:
            if terminal is not None:
                terminal.set()

    def _release_locked(self, token: object) -> None:
        if token not in self._owners:
            return
        if len(self._owners) > 1:
            self._owners.remove(token)
            return

        current = sys.modules.get("__main__", _MISSING_MAIN)
        host = self._host
        allowed = current is host or current in self._kernel_candidates
        self._owners.remove(token)
        self._host = _MISSING_MAIN
        self._kernel_candidates.clear()
        self._pending.clear()
        self._terminals.clear()
        self._reapers.clear()
        if not allowed:
            raise ProtocolError(
                "Another runtime replaced the host main module during shutdown"
            )
        if host is _MISSING_MAIN:
            sys.modules.pop("__main__", None)
        else:
            sys.modules["__main__"] = cast(ModuleType, host)


_MAIN_MODULES = _MainModuleOwnership()


def _kernel_threads(sessions: tuple[Any, ...]) -> tuple[Thread, ...]:
    threads: dict[int, Thread] = {}
    for session in sessions:
        manager = getattr(session, "_kernel_manager", None)
        task = getattr(manager, "kernel_task", None)
        if isinstance(task, Thread):
            threads.setdefault(id(task), task)
    return tuple(threads.values())


def _session_notebook_paths(sessions: tuple[Any, ...]) -> frozenset[str]:
    paths: set[str] = set()
    for session in sessions:
        file_manager = getattr(session, "app_file_manager", None)
        path = getattr(file_manager, "path", None)
        if isinstance(path, str):
            paths.add(path)
    return frozenset(paths)


def _join_kernel_threads(threads: tuple[Thread, ...]) -> None:
    deadline = monotonic() + _KERNEL_JOIN_TIMEOUT
    caller = current_thread()
    for thread in threads:
        if thread is caller or thread.ident is None:
            continue
        thread.join(max(0.0, deadline - monotonic()))
    alive = tuple(thread for thread in threads if thread.is_alive())
    if alive:
        raise ProcessCleanupError(
            "Programmatic Marimo kernels did not stop within "
            f"{_KERNEL_JOIN_TIMEOUT:g} seconds"
        )


class _ProgrammaticApp:
    def __init__(
        self,
        app: ASGIApp,
        state: Any,
        configured_base_url: str,
        presentation: _PresentationApplication,
    ) -> None:
        self.app = app
        self.state = state
        self.configured_base_url = configured_base_url
        self.presentation = presentation
        self._public_base_url: str | None = None
        self._lock = Lock()

    @asynccontextmanager
    async def lifespan(
        self,
        owned_kernel_threads: set[Thread],
    ) -> AsyncIterator[None]:
        shutdown_attempted = False

        async def shutdown_manager() -> None:
            nonlocal shutdown_attempted
            if shutdown_attempted:
                return
            shutdown_attempted = True
            manager = self.state.session_manager
            sessions = tuple(manager.sessions.values())
            threads = set(_kernel_threads(sessions))
            owned_kernel_threads.update(threads)
            if threads:
                _MAIN_MODULES.observe_kernel_module(_session_notebook_paths(sessions))
            first_failure: BaseException | None = None
            retry_failure: BaseException | None = None
            try:
                manager.shutdown()
            except BaseException as error:
                first_failure = error
                try:
                    manager.shutdown()
                except BaseException as retry_error:
                    retry_failure = retry_error
            threads.update(_kernel_threads(sessions))
            owned_kernel_threads.update(threads)
            cancellation: asyncio.CancelledError | None = None
            try:
                if threads:
                    _result, cancellation = await settle_ownership(
                        asyncio.to_thread(
                            _join_kernel_threads,
                            tuple(threads),
                        )
                    )
            except BaseException as cleanup_failure:
                if first_failure is not None:
                    if retry_failure is not None:
                        retry_failure.__cause__ = cleanup_failure
                        raise first_failure from retry_failure
                    raise first_failure from cleanup_failure
                raise
            if first_failure is not None:
                if retry_failure is not None:
                    raise first_failure from retry_failure
                raise first_failure
            propagate_cancellation(cancellation)

        try:
            async with self.presentation.lifespan():
                try:
                    yield
                finally:
                    await shutdown_manager()
        finally:
            await shutdown_manager()

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return

        public_base_url = effective_base_url(scope, self.configured_base_url)
        with self._lock:
            if self._public_base_url is None:
                self._public_base_url = public_base_url
                self.state.base_url = public_base_url
            elif self._public_base_url != public_base_url:
                raise ProtocolError(
                    "A programmatic Marimo app must use one public mount path"
                )

        if scope["type"] != "http" or not public_base_url:
            await self.app(scope, receive, send)
            return

        async def send_with_public_base(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers: list[tuple[bytes, bytes]] = []
                for name, value in message.get("headers", []):
                    if name.lower() == b"location" and (
                        value == b"/auth/login" or value.startswith(b"/auth/login?")
                    ):
                        value = (f"{public_base_url}{value.decode('latin-1')}").encode(
                            "latin-1"
                        )
                    headers.append((name, value))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_public_base)


class _ProgrammaticMiddleware:
    def __init__(self, notebook: Path, adapter_factory: _AdapterFactory) -> None:
        self.notebook = notebook
        self.adapter_factory = adapter_factory

    def __call__(self, app: ASGIApp) -> ASGIApp:
        state = getattr(app, "state", None)
        session_manager = getattr(state, "session_manager", None)
        if state is None or session_manager is None:
            raise ProtocolError("Marimo did not expose single-notebook server state")
        config_manager = config_manager_at_notebook(
            state.config_manager,
            self.notebook,
        )
        state.config_manager = config_manager
        session_manager._config_manager = config_manager
        state._marimo_studio_configured_notebook = self.notebook
        presentation = _presentation_middleware(app, self.adapter_factory)
        return _ProgrammaticApp(
            app,
            state,
            str(getattr(state, "base_url", "")),
            presentation,
        )


class _PresentationCapture:
    def __init__(self, factory: Callable[..., ASGIApp]) -> None:
        self.factory = factory
        self.presentation: _PresentationApplication | None = None

    def __call__(self, app: ASGIApp, *args: Any, **kwargs: Any) -> ASGIApp:
        if self.presentation is not None:
            raise ProtocolError("Marimo built the presentation middleware twice")
        presentation = self.factory(app, *args, **kwargs)
        if not callable(getattr(presentation, "lifespan", None)):
            raise ProtocolError("Studio did not expose its application lifespan")
        self.presentation = cast(_PresentationApplication, presentation)
        return presentation


def _presentation_middleware(
    app: ASGIApp,
    adapter_factory: _AdapterFactory,
) -> _PresentationApplication:
    build = getattr(app, "build_middleware_stack", None)
    if not callable(build):
        raise ProtocolError("Marimo did not expose its middleware stack")
    if getattr(app, "middleware_stack", None) is not None:
        raise ProtocolError("Marimo built its middleware before Studio could own it")
    entries = getattr(app, "user_middleware", None)
    if not isinstance(entries, list):
        raise ProtocolError("Marimo did not expose its application middleware")
    matches = [
        (index, entry)
        for index, entry in enumerate(entries)
        if getattr(entry, "kwargs", {}).get("adapter_factory") is adapter_factory
    ]
    if len(matches) != 1:
        raise ProtocolError("Marimo did not install one presentation middleware")
    index, entry = matches[0]
    capture = _PresentationCapture(entry.cls)
    entries[index] = Middleware(capture, *entry.args, **entry.kwargs)
    cast(Any, app).middleware_stack = build()
    if capture.presentation is None:
        raise ProtocolError("Marimo did not build the presentation middleware")
    return capture.presentation


class _ProgrammaticLifespans:
    def __init__(
        self,
        native: _LifespanContext,
        mounted: tuple[_ProgrammaticApp, ...],
    ) -> None:
        self._native = native
        self._mounted = mounted

    @asynccontextmanager
    async def _manager(self, app: Any) -> AsyncIterator[Any]:
        main_owner = _MAIN_MODULES.open()
        owned_kernel_threads: set[Thread] = set()
        primary_failure: BaseException | None = None
        try:
            try:
                async with AsyncExitStack() as stack:
                    state = await stack.enter_async_context(self._native(app))
                    for mounted in self._mounted:
                        await stack.enter_async_context(
                            mounted.lifespan(owned_kernel_threads)
                        )
                    yield state
            except BaseException as error:
                primary_failure = error
        finally:
            threads = tuple(owned_kernel_threads)
            try:
                if any(thread.is_alive() for thread in threads):
                    _MAIN_MODULES.defer(main_owner, threads)
                else:
                    _MAIN_MODULES.close(main_owner)
            except BaseException as cleanup_failure:
                if primary_failure is not None:
                    raise primary_failure from cleanup_failure
                raise
        if primary_failure is not None:
            raise primary_failure

    def __call__(self, app: Any) -> AbstractAsyncContextManager[Any]:
        return self._manager(app)


def programmatic_middleware(
    notebook: Path,
    adapter_factory: _AdapterFactory,
) -> _ProgrammaticMiddleware:
    """Bind notebook configuration and its public mount to a Marimo app."""
    return _ProgrammaticMiddleware(notebook, adapter_factory)


def own_programmatic_lifespans(app: ASGIApp) -> ASGIApp:
    """Attach mounted notebook lifespans to the returned Marimo application."""
    router = getattr(app, "router", None)
    routes = getattr(app, "routes", None)
    if router is None or routes is None:
        raise ProtocolError("Marimo did not return a routable ASGI application")
    native = getattr(router, "lifespan_context", None)
    if isinstance(native, _ProgrammaticLifespans):
        return app
    if not callable(native):
        raise ProtocolError("Marimo did not expose its application lifespan")
    mounted_by_identity: dict[int, _ProgrammaticApp] = {}
    for route in routes:
        route_app = getattr(route, "app", None)
        if isinstance(route_app, _ProgrammaticApp):
            mounted_by_identity.setdefault(id(route_app), route_app)
    mounted = tuple(mounted_by_identity.values())
    if not mounted:
        raise ProtocolError("Marimo did not mount the configured notebook")
    router.lifespan_context = _ProgrammaticLifespans(
        cast(_LifespanContext, native),
        mounted,
    )
    return app
