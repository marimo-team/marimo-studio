"""Read and notify live Marimo sessions through an opaque server handle."""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from time import monotonic
from typing import Literal
from weakref import ReferenceType, WeakKeyDictionary, WeakSet
from weakref import ref as weakref_ref

from marimo._messaging.notification import (
    QueryParamsSetNotification,
    ReloadNotification,
)
from marimo._messaging.serde import serialize_kernel_message
from marimo._session.session import Session
from marimo._session.types import KernelState

from marimo_studio._compat.kernel_values.session import read_session_values
from marimo_studio._compat.runtime_requests import instantiate_notebook_request
from marimo_studio._compat.server.gateway import context_handle
from marimo_studio._delivery.urls import (
    DOCUMENT_REPLAY_QUERY_PARAM,
    EDITOR_BINDING_CAPABILITY_QUERY_PARAM,
    HOST_SESSION_HANDOFF_QUERY_PARAM,
    PRIVATE_QUERY_KEYS,
    STUDIO_CLIENT_QUERY_PARAM,
)
from marimo_studio._notebook.cell_refs import cell_refs
from marimo_studio._notebook.records import LiveCellIdentity, LiveCellSnapshot
from marimo_studio._processes.latest_work import LatestWork
from marimo_studio._processes.ownership import (
    propagate_cancellation,
    settle_ownership,
)
from marimo_studio._server.ports import EditorSessionIdentity, SessionOwner
from marimo_studio._server.presentation.ports import ProjectionUnavailable
from marimo_studio._server.query import (
    CanonicalPublicQuery,
    canonical_public_query,
)
from marimo_studio._server.records import ServerContext
from marimo_studio.errors._internal import RuntimeStartupError, RuntimeSyncError

_SESSION_PATTERN = re.compile(r"s_[a-z0-9]{6}")
_NATIVE_INSTANTIATION_TIMEOUT_SECONDS = 30.0


@dataclass(frozen=True)
class _LiveCellCapture:
    session_owner: int
    document_generation: int
    cells: tuple[tuple[str, str, str], ...]
    executed_cells: tuple[tuple[str, str], ...]
    graph_parents: tuple[tuple[str, tuple[str, ...]], ...] | None


def _is_session_id(value: object) -> bool:
    return isinstance(value, str) and _SESSION_PATTERN.fullmatch(value) is not None


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
    return canonical_public_query(items)


def session_creation_query_matches(
    session: object,
    query: Iterable[tuple[str, str]],
) -> bool:
    """Match public query semantics against native session creation metadata."""
    expected = _session_creation_query(session)
    return expected is not None and expected == canonical_public_query(query)


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


def _capture_live_cells(
    context: ServerContext,
    session_id: str | None,
    *,
    include_dependency_closures: bool,
    session_owner: Callable[[Session], int],
) -> _LiveCellCapture | None:
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
    document = session.document
    rows = tuple((str(row.id), row.code, row.name) for row in document.cells)
    ordered_ids = tuple(runtime_id for runtime_id, _code, _name in rows)
    executed_code = {
        str(cell_id): code
        for cell_id, code in session.session_view.last_executed_code.copy().items()
    }
    ordered_executed_cells = tuple(
        (runtime_id, executed_code[runtime_id])
        for runtime_id in ordered_ids
        if runtime_id in executed_code
    )
    graph_parents: tuple[tuple[str, tuple[str, ...]], ...] | None = None
    if include_dependency_closures:
        graph = session.app_file_manager.app.graph
        with graph.lock:
            graph_ids = {str(cell_id): cell_id for cell_id in graph.cells}
            graph_parents = tuple(
                (
                    runtime_id,
                    tuple(
                        candidate
                        for candidate in ordered_ids
                        if candidate in graph_ids
                        and graph_ids[candidate]
                        in graph.topology.parents.get(graph_ids[runtime_id], ())
                    ),
                )
                for runtime_id in ordered_ids
                if runtime_id in graph_ids
            )
    return _LiveCellCapture(
        session_owner=session_owner(session),
        document_generation=document.version,
        cells=rows,
        executed_cells=ordered_executed_cells,
        graph_parents=graph_parents,
    )


def _dependency_closures(
    ordered_ids: tuple[str, ...],
    graph_parents: tuple[tuple[str, tuple[str, ...]], ...] | None,
) -> dict[str, tuple[str, ...]]:
    if graph_parents is None:
        return {}
    parents = dict(graph_parents)
    closures: dict[str, tuple[str, ...]] = {}
    for runtime_id in ordered_ids:
        if runtime_id not in parents:
            continue
        ancestors: set[str] = set()
        pending = list(parents[runtime_id])
        while pending:
            parent = pending.pop()
            if parent in ancestors:
                continue
            ancestors.add(parent)
            pending.extend(parents.get(parent, ()))
        closures[runtime_id] = tuple(
            candidate
            for candidate in ordered_ids
            if candidate == runtime_id or candidate in ancestors
        )
    return closures


def _materialize_live_cells(capture: _LiveCellCapture) -> LiveCellSnapshot:
    ordered_ids = tuple(runtime_id for runtime_id, _code, _name in capture.cells)
    refs = cell_refs(code for _runtime_id, code, _name in capture.cells)
    executed_refs = cell_refs(code for _runtime_id, code in capture.executed_cells)
    names: dict[str, list[LiveCellIdentity]] = {}
    for ref, (runtime_id, _code, name) in zip(
        refs,
        capture.cells,
        strict=True,
    ):
        if name == "_":
            continue
        names.setdefault(name, []).append(
            LiveCellIdentity(ref=ref, runtime_id=runtime_id)
        )
    return LiveCellSnapshot(
        owner=f"session:{capture.session_owner:x}",
        generation=hashlib.sha256(repr(capture).encode("utf-8")).hexdigest(),
        ids={
            ref: runtime_id
            for ref, (runtime_id, _code, _name) in zip(
                refs,
                capture.cells,
                strict=True,
            )
        },
        names={name: tuple(identities) for name, identities in names.items()},
        dependency_closures=_dependency_closures(
            ordered_ids,
            capture.graph_parents,
        ),
        current_refs={
            runtime_id: ref
            for ref, (runtime_id, _cell) in zip(
                executed_refs,
                capture.executed_cells,
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
        self._runtime_owners: WeakKeyDictionary[Session, int] = WeakKeyDictionary()
        self._next_runtime_owner = 0
        self._live_materializer = LatestWork[LiveCellSnapshot](
            superseded_error=lambda: RuntimeSyncError(
                "A newer Marimo session generation replaced this capture."
            ),
            closed_error=lambda: RuntimeSyncError(
                "Marimo session state is shutting down."
            ),
        )

    def is_session_id(self, value: object) -> bool:
        return _is_session_id(value)

    async def close(self) -> None:
        """Cancel and gather every adapter-owned startup barrier."""
        if self._closed:
            return
        self._closed = True
        failure: BaseException | None = None
        try:
            await self._live_materializer.close()
        except BaseException as error:
            failure = error
        tasks = tuple(set(self._starting.values()))
        for task in tasks:
            task.cancel()
        cancellation: asyncio.CancelledError | None = None
        if tasks:
            _results, cancellation = await settle_ownership(
                asyncio.gather(*tasks, return_exceptions=True)
            )
        self._starting.clear()
        self._waiting_since.clear()
        self._start_failures.clear()
        self._instantiation_requested.clear()
        self._started.clear()
        self._runtime_owners.clear()
        if failure is not None:
            raise failure
        propagate_cancellation(cancellation)

    def exists(self, context: ServerContext, session_id: str) -> bool:
        return current_session(context, session_id) is not None

    def request_studio_reload(
        self,
        context: ServerContext,
        session_id: str,
        *,
        host_handoff: str | None = None,
    ) -> bool:
        """Reload the saving consumer after its notebook receives a filename."""
        from marimo._types.ids import ConsumerId

        session = current_session(context, session_id)
        if session is None:
            return False
        consumer = session.room.get_consumer(ConsumerId(session_id))
        file_key = getattr(getattr(consumer, "params", None), "file_key", None)
        if file_key is None:
            file_key = getattr(session, "initialization_id", None)
        if (
            consumer is None
            or not isinstance(file_key, str)
            or not file_key.startswith("__new__")
        ):
            return False
        consumer.notify(
            serialize_kernel_message(
                QueryParamsSetNotification("session_id", session_id)
            )
        )
        if host_handoff is not None:
            consumer.notify(
                serialize_kernel_message(
                    QueryParamsSetNotification(
                        HOST_SESSION_HANDOFF_QUERY_PARAM, host_handoff
                    )
                )
            )
        consumer.notify(
            serialize_kernel_message(
                QueryParamsSetNotification(DOCUMENT_REPLAY_QUERY_PARAM, "1")
            )
        )
        consumer.notify(serialize_kernel_message(ReloadNotification()))
        return True

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
        """Read the Studio identity of one attached native consumer."""
        from marimo._types.ids import ConsumerId

        session = current_session(context, session_id)
        if session is None:
            return None
        consumer = session.room.get_consumer(ConsumerId(session_id))
        connection = getattr(consumer, "websocket", None) or getattr(
            consumer, "request", None
        )
        query = getattr(connection, "query_params", None)
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

    def _runtime_owner(self, session: Session) -> int:
        owner = self._runtime_owners.get(session)
        if owner is not None:
            return owner
        self._next_runtime_owner += 1
        self._runtime_owners[session] = self._next_runtime_owner
        return self._next_runtime_owner

    async def live_cells(
        self,
        context: ServerContext,
        session_id: str | None,
        *,
        include_dependency_closures: bool,
    ) -> LiveCellSnapshot | None:
        if self._closed:
            raise RuntimeSyncError("Marimo session state is shutting down.")
        capture = _capture_live_cells(
            context,
            session_id,
            include_dependency_closures=include_dependency_closures,
            session_owner=self._runtime_owner,
        )
        if capture is None:
            return None
        snapshot = await self._live_materializer.run(
            capture,
            (capture.session_owner, include_dependency_closures),
            partial(_materialize_live_cells, capture),
        )
        if self._closed:
            raise RuntimeSyncError("Marimo session state is shutting down.")
        current = _capture_live_cells(
            context,
            session_id,
            include_dependency_closures=include_dependency_closures,
            session_owner=self._runtime_owner,
        )
        if current != capture:
            raise RuntimeSyncError(
                "The Marimo session changed while Studio captured runtime bindings."
            )
        return snapshot

    async def control_bindings(
        self, context: ServerContext, session_id: str
    ) -> dict[str, object]:
        from marimo_export.errors import MarimoExportError
        from marimo_export.sessions import connect

        session = current_session(context, session_id)
        if self._closed or session is None or context.internal_url is None:
            raise RuntimeSyncError("The notebook control bindings are unavailable.")
        # Export discovery lists kernel IDs, while Marimo also resolves consumer IDs.
        manager = context_handle(context).session_manager
        canonical_id = next(
            (key for key, current in manager.sessions.items() if current is session),
            None,
        )
        if canonical_id is None:
            raise RuntimeSyncError("The notebook control bindings are unavailable.")
        server = context.internal_url

        def observe() -> dict[str, object]:
            with connect(
                server,
                access_token=context.access_token,
                server_token=context.server_token,
            ) as client:
                observation = client.session(str(canonical_id)).observe_inputs()
                return {
                    object_id: binding.to_value()
                    for object_id, binding in observation.control_bindings.items()
                }

        try:
            bindings = await asyncio.to_thread(observe)
        except MarimoExportError as error:
            raise RuntimeSyncError(str(error)) from error
        if (
            self._closed
            or current_session(context, session_id) is not session
            or manager.sessions.get(canonical_id) is not session
        ):
            raise RuntimeSyncError(
                "The notebook changed while reading control bindings."
            )
        return bindings


def _single_string(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, list) and len(value) == 1 and isinstance(value[0], str):
        return value[0]
    return None
