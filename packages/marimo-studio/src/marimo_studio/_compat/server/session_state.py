"""Read and notify live Marimo sessions through an opaque server handle."""

from __future__ import annotations

import asyncio
import os
import re
from collections.abc import Iterable, Mapping, Sequence
from contextlib import suppress
from functools import partial
from pathlib import Path
from time import monotonic
from typing import Literal
from weakref import ReferenceType, WeakKeyDictionary, WeakSet
from weakref import ref as weakref_ref

from marimo._session.session import Session
from marimo._session.types import KernelState

from marimo_studio._compat.kernel_values.session import read_session_values
from marimo_studio._compat.runtime_requests import instantiate_notebook_request
from marimo_studio._compat.server.gateway import context_handle
from marimo_studio._delivery.urls import (
    EDITOR_BINDING_CAPABILITY_QUERY_PARAM,
    PRIVATE_QUERY_KEYS,
    STUDIO_CLIENT_QUERY_PARAM,
)
from marimo_studio._notebook.cell_refs import cell_refs
from marimo_studio._notebook.records import LiveCellIdentity, LiveCellSnapshot
from marimo_studio._server.ports import EditorSessionIdentity, SessionOwner
from marimo_studio._server.presentation.ports import ProjectionUnavailable
from marimo_studio._server.records import ServerContext
from marimo_studio.errors._internal import RuntimeStartupError, RuntimeSyncError

_SESSION_PATTERN = re.compile(r"s_[a-z0-9]{6}")
_NATIVE_INSTANTIATION_TIMEOUT_SECONDS = 30.0
CanonicalPublicQuery = tuple[tuple[str, tuple[str, ...]], ...]


def _is_session_id(value: object) -> bool:
    return isinstance(value, str) and _SESSION_PATTERN.fullmatch(value) is not None


def _canonical_public_query(
    query: Iterable[tuple[str, str]],
) -> CanonicalPublicQuery:
    values: dict[str, list[str]] = {}
    for key, value in query:
        if key in PRIVATE_QUERY_KEYS:
            continue
        values.setdefault(key, []).append(value)
    return tuple((key, tuple(values[key])) for key in sorted(values))


def _session_creation_query(session: object) -> CanonicalPublicQuery | None:
    manager = getattr(session, "_kernel_manager", None)
    metadata = getattr(manager, "app_metadata", None)
    if metadata is None:
        metadata = getattr(manager, "_app_metadata", None)
    query = getattr(metadata, "query_params", None)
    if not isinstance(query, Mapping):
        return None
    items: list[tuple[str, str]] = []
    for key, value in query.items():
        if not isinstance(key, str):
            return None
        if key in PRIVATE_QUERY_KEYS:
            continue
        if isinstance(value, str):
            items.append((key, value))
            continue
        if (
            isinstance(value, Sequence)
            and not isinstance(value, (str, bytes))
            and value
        ):
            text_values: list[str] = []
            for item in value:
                if not isinstance(item, str):
                    return None
                text_values.append(item)
            items.extend((key, item) for item in text_values)
            continue
        return None
    return _canonical_public_query(items)


def session_creation_query_matches(
    session: object,
    query: Iterable[tuple[str, str]],
) -> bool:
    """Match public query semantics against native session creation metadata."""
    expected = _session_creation_query(session)
    return expected is not None and expected == _canonical_public_query(query)


def current_session(context: ServerContext, session_id: str) -> Session | None:
    """Return an adapter-owned session for internal capability composition."""
    from marimo._types.ids import SessionId

    session = context_handle(context).session_manager.get_session(SessionId(session_id))
    return (
        session
        if session_matches_notebook(
            session,
            file_key=context.file_key,
            notebook=context.notebook,
        )
        else None
    )


def session_matches_notebook(
    session: Session | None,
    *,
    file_key: str,
    notebook: Path,
) -> bool:
    """Return whether a Marimo session belongs to the selected notebook."""
    if session is None:
        return False
    if str(session.initialization_id) == file_key:
        return True
    source = session.app_file_manager.path
    return source is not None and Path(os.path.abspath(source)) == notebook


def _has_notebook_session(context: ServerContext) -> bool:
    manager = context_handle(context).session_manager
    return manager.get_session_by_file_key(context.file_key) is not None


def _live_cells(
    context: ServerContext,
    session_id: str | None,
) -> LiveCellSnapshot | None:
    if session_id is not None:
        session = current_session(context, session_id)
    elif context.mode == "edit":
        session = context_handle(context).session_manager.get_session_by_file_key(
            context.file_key
        )
    else:
        return None
    if session is None:
        if session_id is None or context.mode == "run":
            return None
        raise RuntimeSyncError(
            "The Marimo session is still connecting. Studio will retry shortly."
        )
    rows = tuple(session.document.cells)
    refs = cell_refs(row.code for row in rows)
    ordered_ids = tuple(str(row.id) for row in rows)
    graph = session.app_file_manager.app.graph
    graph_ids = {str(cell_id): cell_id for cell_id in graph.cells}
    executed_code = {
        str(cell_id): code
        for cell_id, code in session.session_view.last_executed_code.items()
    }
    ordered_executed_cells = tuple(
        (runtime_id, executed_code[runtime_id])
        for runtime_id in ordered_ids
        if runtime_id in executed_code
    )
    executed_refs = cell_refs(code for _runtime_id, code in ordered_executed_cells)
    dependency_closures = {
        runtime_id: tuple(
            candidate
            for candidate in ordered_ids
            if candidate
            in {
                runtime_id,
                *(str(cell_id) for cell_id in graph.ancestors(graph_ids[runtime_id])),
            }
        )
        for runtime_id in ordered_ids
        if runtime_id in graph_ids
    }
    names: dict[str, list[LiveCellIdentity]] = {}
    for ref, row in zip(refs, rows, strict=True):
        if row.name == "_":
            continue
        names.setdefault(row.name, []).append(
            LiveCellIdentity(ref=ref, runtime_id=str(row.id))
        )
    return LiveCellSnapshot(
        ids={ref: str(row.id) for ref, row in zip(refs, rows, strict=True)},
        names={name: tuple(identities) for name, identities in names.items()},
        dependency_closures=dependency_closures,
        current_refs={
            runtime_id: ref
            for ref, (runtime_id, _cell) in zip(
                executed_refs,
                ordered_executed_cells,
                strict=True,
            )
        },
    )


class PrivateSessionState:
    """Expose stable session operations backed by the pinned release adapter."""

    def __init__(self) -> None:
        self._closed = False
        self._started: WeakSet[Session] = WeakSet()
        self._instantiation_requested: WeakSet[Session] = WeakSet()
        self._starting: WeakKeyDictionary[Session, asyncio.Task[None]] = (
            WeakKeyDictionary()
        )
        self._waiting_since: WeakKeyDictionary[Session, float] = WeakKeyDictionary()
        self._start_failures: WeakKeyDictionary[Session, str] = WeakKeyDictionary()

    def is_session_id(self, value: object) -> bool:
        return _is_session_id(value)

    async def close(self) -> None:
        """Cancel and gather every adapter-owned startup barrier."""
        if self._closed:
            return
        self._closed = True
        tasks = tuple(set(self._starting.values()))
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._starting.clear()
        self._waiting_since.clear()
        self._start_failures.clear()
        self._instantiation_requested.clear()
        self._started.clear()

    def exists(self, context: ServerContext, session_id: str) -> bool:
        return current_session(context, session_id) is not None

    def matches_creation_query(
        self,
        context: ServerContext,
        session_id: str,
        query: Sequence[tuple[str, str]],
    ) -> bool:
        """Match a request to the public query that created a native session."""
        session = current_session(context, session_id)
        return session is not None and session_creation_query_matches(session, query)

    def ownership(
        self,
        context: ServerContext,
        session_id: str,
    ) -> Literal["unclaimed", "current", "foreign"]:
        return self.owner(context, session_id).state

    def owner(self, context: ServerContext, session_id: str) -> SessionOwner:
        from marimo._types.ids import SessionId

        manager = context_handle(context).session_manager
        session = manager.get_session(SessionId(session_id))
        if session is None:
            return SessionOwner("unclaimed", None)
        state: Literal["current", "foreign"] = (
            "current"
            if session_matches_notebook(
                session,
                file_key=context.file_key,
                notebook=context.notebook,
            )
            else "foreign"
        )
        return SessionOwner(state, session)

    def editor_identity(
        self,
        context: ServerContext,
        session_id: str,
    ) -> EditorSessionIdentity | None:
        """Read the trusted editor identity recorded at native-session creation."""
        session = current_session(context, session_id)
        manager = getattr(session, "_kernel_manager", None)
        metadata = getattr(manager, "app_metadata", None)
        if metadata is None:
            metadata = getattr(manager, "_app_metadata", None)
        query = getattr(metadata, "query_params", None)
        if not isinstance(query, Mapping):
            return None
        client_id = _single_string(query.get(STUDIO_CLIENT_QUERY_PARAM))
        capability = _single_string(query.get(EDITOR_BINDING_CAPABILITY_QUERY_PARAM))
        if client_id is None or capability is None:
            return None
        return EditorSessionIdentity(client_id, capability)

    def retry_startup(
        self,
        context: ServerContext,
        session_id: str,
        expected_claim: object,
    ) -> bool:
        """Clear one failed startup when a new exact editor consumer connects."""
        session = current_session(context, session_id)
        if (
            session is None
            or session is not expected_claim
            or session not in self._start_failures
        ):
            return False
        self._start_failures.pop(session, None)
        self._waiting_since.pop(session, None)
        self._instantiation_requested.discard(session)
        return True

    def ensure_started(
        self,
        context: ServerContext,
        session_id: str,
    ) -> bool:
        """Queue one native Run All after Marimo has queued notebook creation."""
        if self._closed:
            raise RuntimeStartupError("Notebook startup is shutting down.")
        session = current_session(context, session_id)
        if session is None:
            return False
        if session in self._started:
            return True
        failure = self._start_failures.get(session)
        if failure is not None:
            raise RuntimeStartupError(failure)
        task = self._starting.get(session)
        if task is not None:
            return False
        document_cells = session.document.cells
        expected = {str(row.id) for row in document_cells if row.code.strip()}
        if not expected:
            self._waiting_since.pop(session, None)
            self._started.add(session)
            return True
        last_executed_code = session.session_view.last_executed_code
        queued = {str(cell_id) for cell_id in last_executed_code}
        if not queued:
            waiting_since = self._waiting_since.setdefault(session, monotonic())
            if (
                session.kernel_state() is KernelState.RUNNING
                and session not in self._instantiation_requested
            ):
                session.instantiate(
                    instantiate_notebook_request(auto_run=False),
                    http_request=None,
                )
                self._instantiation_requested.add(session)
            if monotonic() - waiting_since >= _NATIVE_INSTANTIATION_TIMEOUT_SECONDS:
                failure = (
                    "Marimo did not initialize the notebook within "
                    f"{_NATIVE_INSTANTIATION_TIMEOUT_SECONDS:g} seconds. "
                    "Reload the editor to retry."
                )
                self._start_failures[session] = failure
                raise RuntimeStartupError(failure)
            return False
        # Any recorded code proves Marimo queued its native CreateNotebook command.
        # The browser can legitimately omit hidden or locally removed cells, so exact
        # parity with the saved document is not a valid initialization barrier.
        self._waiting_since.pop(session, None)
        self._instantiation_requested.discard(session)
        task = asyncio.create_task(self._start(session, session_id))
        self._starting[session] = task
        task.add_done_callback(partial(self._finish_start, weakref_ref(session)))
        return False

    def _finish_start(
        self,
        session_ref: ReferenceType[Session],
        task: asyncio.Task[None],
    ) -> None:
        error = None if task.cancelled() else task.exception()
        session = session_ref()
        if session is None:
            return
        if self._starting.get(session) is task:
            self._starting.pop(session, None)
        self._waiting_since.pop(session, None)
        if task.cancelled() or (
            isinstance(error, ProjectionUnavailable) and error.transient
        ):
            return
        if error is not None:
            self._start_failures[session] = str(error) or "Notebook startup failed."
        else:
            self._started.add(session)

    @staticmethod
    async def _start(session: Session, session_id: str) -> None:
        from marimo._runtime.commands import ExecuteStaleCellsCommand

        session.put_control_request(
            ExecuteStaleCellsCommand(),
            from_consumer_id=None,
        )
        barrier = asyncio.create_task(
            read_session_values(
                session,
                "studio-startup",
                (),
                consumer_id=session_id,
                timeout=None,
            )
        )
        try:
            while True:
                completed, _pending = await asyncio.wait((barrier,), timeout=0.25)
                if completed:
                    await barrier
                    return
                exit_info = session.kernel_exit_info()
                if exit_info is not None:
                    raise RuntimeStartupError(exit_info.message)
        finally:
            if not barrier.done():
                barrier.cancel()
                with suppress(asyncio.CancelledError):
                    await barrier

    def has_notebook_session(self, context: ServerContext) -> bool:
        return _has_notebook_session(context)

    def live_cells(
        self,
        context: ServerContext,
        session_id: str | None,
    ) -> LiveCellSnapshot | None:
        return _live_cells(context, session_id)


def _single_string(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, list) and len(value) == 1 and isinstance(value[0], str):
        return value[0]
    return None
