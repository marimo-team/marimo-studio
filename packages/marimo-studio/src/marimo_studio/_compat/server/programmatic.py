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

from marimo._runtime import patches as marimo_patches
from marimo._server.session_manager import SessionManager
from starlette.middleware import Middleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from marimo_studio._compat.patch import CompositeCloseHandle, ReversiblePatch
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
from marimo_studio._server.route_policy import StudioRoutePolicy
from marimo_studio._server.security import SecurityPolicy
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
        self._owners: dict[object, frozenset[str]] = {}
        self._manager_owners: dict[int, object] = {}
        self._patch_handles: dict[object, CompositeCloseHandle] = {}
        self._host: ModuleType | object = _MISSING_MAIN
        self._kernel_candidates: dict[ModuleType, Thread] = {}
        self._owned_kernel_threads: set[Thread] = set()
        self._owner_kernel_threads: dict[object, set[Thread]] = {}
        self._pending: dict[object, tuple[Thread, ...]] = {}
        self._terminals: dict[object, Event] = {}
        self._reapers: dict[object, Thread] = {}
        self._failed_releases: set[object] = set()
        self._deferred_error: BaseException | None = None
        self._patch_generation: object | None = None
        self._main_patch = ReversiblePatch(
            "programmatic-main-module",
            marimo_patches,
            "patch_sys_module",
            self._patch_replacement,
        )
        self._session_close_patch = ReversiblePatch(
            "programmatic-session-close",
            SessionManager,
            "close_session",
            self._session_close_replacement,
        )

    def _patch_replacement(
        self,
        native: Callable[[ModuleType], None],
    ) -> Callable[[ModuleType], None]:
        generation = object()
        self._patch_generation = generation

        def patch(module: ModuleType) -> None:
            with self._lock:
                if self._patch_generation is not generation:
                    return
                native(module)
                path = getattr(module, "__file__", None)
                if not isinstance(path, str):
                    return
                if any(path in paths for paths in self._owners.values()):
                    self._kernel_candidates[module] = current_thread()

        return patch

    def _session_close_replacement(
        self,
        native: Callable[[SessionManager, Any], bool],
    ) -> Callable[[SessionManager, Any], bool]:
        def close(manager: SessionManager, session_id: Any) -> bool:
            with self._lock:
                token = self._manager_owners.get(id(manager))
                if token in self._owners:
                    session = manager.sessions.get(session_id)
                    if session is not None:
                        self._claim_kernel_threads_locked(
                            token,
                            _kernel_threads((session,)),
                        )
            return native(manager, session_id)

        return close

    def open(
        self,
        notebook_paths: frozenset[str],
        session_managers: tuple[SessionManager, ...] = (),
        kernel_threads: set[Thread] | None = None,
    ) -> object:
        token = object()
        with self._lock:
            self._reap_settled_locked()
            self._retry_failed_releases_locked()
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
                self._owned_kernel_threads.clear()
            session_patch = self._session_close_patch.open()
            try:
                main_patch = self._main_patch.open()
            except BaseException:
                session_patch.close()
                raise
            self._owners[token] = notebook_paths
            self._owner_kernel_threads[token] = (
                set() if kernel_threads is None else kernel_threads
            )
            self._patch_handles[token] = CompositeCloseHandle(
                (main_patch, session_patch)
            )
            for manager in session_managers:
                self._manager_owners[id(manager)] = token
        return token

    def defer(self, token: object, threads: tuple[Thread, ...]) -> Event:
        with self._lock:
            if token not in self._owners:
                terminal = Event()
                terminal.set()
                return terminal
            self._claim_kernel_threads_locked(token, threads)
            return self._defer_locked(token)

    def close(self, token: object, threads: tuple[Thread, ...] = ()) -> None:
        with self._lock:
            self._reap_settled_locked()
            if token in self._pending:
                return
            self._claim_kernel_threads_locked(token, threads)
            if any(
                thread.is_alive()
                for thread in self._owner_kernel_threads.get(token, ())
            ):
                self._defer_locked(token)
                return
            try:
                self._release_locked(token)
            except BaseException:
                if token in self._owners:
                    self._failed_releases.add(token)
                raise

    def _claim_kernel_threads_locked(
        self,
        token: object,
        threads: tuple[Thread, ...],
    ) -> None:
        if token not in self._owners:
            return
        self._owned_kernel_threads.update(threads)
        self._owner_kernel_threads[token].update(threads)

    def _defer_locked(self, token: object) -> Event:
        existing = self._terminals.get(token)
        if existing is not None:
            return existing
        terminal = Event()
        threads = tuple(self._owner_kernel_threads[token])
        self._pending[token] = threads
        self._terminals[token] = terminal
        if all(not thread.is_alive() for thread in threads):
            self._settle_pending_locked(token)
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
        except BaseException as start_error:
            self._reapers.pop(token, None)
            self._pending.pop(token, None)
            self._terminals.pop(token, None)
            try:
                self._release_locked(token)
            except BaseException as cleanup_error:
                if token in self._owners:
                    self._failed_releases.add(token)
                raise start_error from cleanup_error
            finally:
                terminal.set()
            raise
        return terminal

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
        terminal = self._terminals.get(token)
        try:
            self._release_locked(token)
        except BaseException as error:
            self._deferred_error = error if token in self._owners else None
            raise
        else:
            self._pending.pop(token, None)
            self._terminals.pop(token, None)
            self._reapers.pop(token, None)
            self._deferred_error = None
        finally:
            if terminal is not None:
                terminal.set()

    def _retry_failed_releases_locked(self) -> None:
        for token in tuple(self._failed_releases):
            if any(
                thread.is_alive()
                for thread in self._owner_kernel_threads.get(token, ())
            ):
                raise ProcessCleanupError(
                    "A programmatic Marimo kernel is still shutting down"
                )
            self._release_locked(token)
            self._failed_releases.discard(token)

    def _release_locked(self, token: object) -> None:
        if token not in self._owners:
            return
        if len(self._owners) > 1:
            self._patch_handles[token].close()
            self._patch_handles.pop(token)
            self._owners.pop(token)
            self._owner_kernel_threads.pop(token, None)
            self._remove_manager_owners_locked(token)
            self._failed_releases.discard(token)
            return

        current = sys.modules.get("__main__", _MISSING_MAIN)
        host = self._host
        publisher = (
            self._kernel_candidates.get(current)
            if isinstance(current, ModuleType)
            else None
        )
        allowed = current is host or publisher in self._owned_kernel_threads
        self._patch_handles[token].close()
        self._patch_generation = None
        self._patch_handles.pop(token)
        self._owners.pop(token)
        self._owner_kernel_threads.pop(token, None)
        self._remove_manager_owners_locked(token)
        self._host = _MISSING_MAIN
        self._kernel_candidates.clear()
        self._owned_kernel_threads.clear()
        self._owner_kernel_threads.clear()
        self._patch_handles.clear()
        self._manager_owners.clear()
        self._pending.clear()
        self._terminals.clear()
        self._reapers.clear()
        self._failed_releases.clear()
        self._deferred_error = None
        if not allowed:
            raise ProtocolError(
                "Another runtime replaced the host main module during shutdown"
            )
        if host is _MISSING_MAIN:
            sys.modules.pop("__main__", None)
        else:
            sys.modules["__main__"] = cast(ModuleType, host)

    def _remove_manager_owners_locked(self, token: object) -> None:
        owned = tuple(
            identity
            for identity, manager_owner in self._manager_owners.items()
            if manager_owner is token
        )
        for identity in owned:
            self._manager_owners.pop(identity, None)


_MAIN_MODULES = _MainModuleOwnership()


def _kernel_threads(sessions: tuple[Any, ...]) -> tuple[Thread, ...]:
    threads: dict[int, Thread] = {}
    for session in sessions:
        manager = getattr(session, "_kernel_manager", None)
        task = getattr(manager, "kernel_task", None)
        if isinstance(task, Thread):
            threads.setdefault(id(task), task)
    return tuple(threads.values())


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
        notebook: Path,
        app: ASGIApp,
        state: Any,
        configured_base_url: str,
        presentation: _PresentationApplication,
    ) -> None:
        self.notebook = notebook
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
    def __init__(
        self,
        notebook: Path,
        adapter_factory: _AdapterFactory,
        security_policy: SecurityPolicy,
        route_policy: StudioRoutePolicy | None,
    ) -> None:
        self.notebook = notebook
        self.adapter_factory = adapter_factory
        self.security_policy = security_policy
        self.route_policy = route_policy

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
        presentation = _presentation_middleware(
            app,
            self.adapter_factory,
            self.security_policy,
            self.route_policy,
        )
        return _ProgrammaticApp(
            self.notebook,
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
    security_policy: SecurityPolicy,
    route_policy: StudioRoutePolicy | None,
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
    kwargs = dict(entry.kwargs)
    kwargs["security_policy"] = security_policy
    if route_policy is not None:
        kwargs["route_policy"] = route_policy
    entries[index] = Middleware(capture, *entry.args, **kwargs)
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
        owned_kernel_threads: set[Thread] = set()
        main_owner = _MAIN_MODULES.open(
            frozenset(str(mounted.notebook) for mounted in self._mounted),
            tuple(mounted.state.session_manager for mounted in self._mounted),
            owned_kernel_threads,
        )
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
            cancellation: asyncio.CancelledError | None = None
            try:
                if threads:
                    _result, cancellation = await settle_ownership(
                        asyncio.to_thread(_join_kernel_threads, threads)
                    )
            except BaseException as cleanup_failure:
                try:
                    if any(thread.is_alive() for thread in threads):
                        _MAIN_MODULES.defer(main_owner, threads)
                    else:
                        _MAIN_MODULES.close(main_owner, threads)
                except BaseException as ownership_failure:
                    if primary_failure is not None:
                        raise primary_failure from ownership_failure
                    raise cleanup_failure from ownership_failure
                if primary_failure is not None:
                    raise primary_failure from cleanup_failure
                raise
            try:
                if any(thread.is_alive() for thread in threads):
                    _MAIN_MODULES.defer(main_owner, threads)
                else:
                    _MAIN_MODULES.close(main_owner, threads)
            except BaseException as cleanup_failure:
                if primary_failure is not None:
                    raise primary_failure from cleanup_failure
                raise
            propagate_cancellation(cancellation)
        if primary_failure is not None:
            raise primary_failure

    def __call__(self, app: Any) -> AbstractAsyncContextManager[Any]:
        return self._manager(app)


def programmatic_middleware(
    notebook: Path,
    adapter_factory: _AdapterFactory,
    security_policy: SecurityPolicy,
    *,
    route_policy: StudioRoutePolicy | None = None,
) -> _ProgrammaticMiddleware:
    """Bind notebook configuration and its public mount to a Marimo app."""
    return _ProgrammaticMiddleware(
        notebook,
        adapter_factory,
        security_policy,
        route_policy,
    )


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
