"""Read and notify live Marimo sessions through an opaque server handle."""

from __future__ import annotations

import re
from pathlib import Path

from marimo._session.session import Session

from marimo_studio._capabilities import ServerContext
from marimo_studio._cell_refs import cell_refs
from marimo_studio._compat.server.gateway import context_handle
from marimo_studio.errors import RuntimeSyncError
from marimo_studio.types import LiveCellIdentity, LiveCellSnapshot

_SESSION_PATTERN = re.compile(r"s_[a-z0-9]{6}")


def _is_session_id(value: object) -> bool:
    return isinstance(value, str) and _SESSION_PATTERN.fullmatch(value) is not None


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
    initialization_id = str(session.initialization_id)
    source = session.app_file_manager.path
    path = Path(source).resolve() if source is not None else None
    return initialization_id == file_key or path == notebook


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
    )


class PrivateSessionState:
    """Expose stable session operations backed by the pinned release adapter."""

    def is_session_id(self, value: object) -> bool:
        return _is_session_id(value)

    def exists(self, context: ServerContext, session_id: str) -> bool:
        return current_session(context, session_id) is not None

    def has_notebook_session(self, context: ServerContext) -> bool:
        return _has_notebook_session(context)

    def live_cells(
        self,
        context: ServerContext,
        session_id: str | None,
    ) -> LiveCellSnapshot | None:
        return _live_cells(context, session_id)


__all__ = [
    "PrivateSessionState",
    "current_session",
    "session_matches_notebook",
]
