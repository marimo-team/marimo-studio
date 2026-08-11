"""Read authorization and live session state from Marimo."""

from __future__ import annotations

import hmac
import re
from pathlib import Path
from urllib.parse import parse_qs

from marimo._session.session import Session
from starlette.datastructures import Headers
from starlette.types import Scope

from marimo_studio._cell_refs import cell_refs
from marimo_studio._compat.server.models import ServerContext
from marimo_studio._urls import ACTIVE_VIEW_QUERY_PARAM
from marimo_studio.errors import RuntimeSyncError
from marimo_studio.types import LiveCellIdentity, LiveCellSnapshot

_SESSION_PATTERN = re.compile(r"s_[a-z0-9]{6}")


def server_token_matches(scope: Scope, expected: str) -> bool:
    """Validate Marimo's server token for a Studio mutation route."""
    supplied = Headers(scope=scope).get("Marimo-Server-Token")
    return supplied is not None and hmac.compare_digest(supplied, expected)


def has_read_access(scope: Scope) -> bool:
    auth = scope.get("auth")
    scopes = getattr(auth, "scopes", ())
    return "read" in scopes


def has_edit_access(scope: Scope) -> bool:
    auth = scope.get("auth")
    scopes = getattr(auth, "scopes", ())
    return "edit" in scopes


def has_access_token(scope: Scope) -> bool:
    raw = scope.get("query_string", b"")
    query = parse_qs(bytes(raw).decode("latin-1"), keep_blank_values=True)
    return "access_token" in query


def is_session_id(value: object) -> bool:
    """Return whether a value follows Marimo's current session ID grammar."""
    return isinstance(value, str) and _SESSION_PATTERN.fullmatch(value) is not None


def current_session(context: ServerContext, session_id: str) -> Session | None:
    from marimo._types.ids import SessionId

    session = context._session_manager.get_session(SessionId(session_id))
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


def has_notebook_session(context: ServerContext) -> bool:
    """Return whether edit mode has a primary session for this notebook."""
    return (
        context._session_manager.get_session_by_file_key(context.file_key) is not None
    )


async def reload_page_into_studio(
    context: ServerContext,
    view_name: str,
    session_id: str | None = None,
) -> None:
    """Reload the native editor into a selected Studio view after code mode."""
    from marimo._messaging.notification import (
        QueryParamsSetNotification,
        ReloadNotification,
    )

    session = (
        current_session(context, session_id)
        if session_id is not None
        else context._session_manager.get_session_by_file_key(context.file_key)
    )
    if session is None:
        return

    # Code mode holds this lock until its result has been delivered. Waiting
    # here keeps the navigation from aborting the agent call that requested it.
    async with session.scratchpad_lock:
        session.notify(
            QueryParamsSetNotification(ACTIVE_VIEW_QUERY_PARAM, view_name),
            from_consumer_id=None,
        )
        session.notify(ReloadNotification(), from_consumer_id=None)


def live_cells(
    context: ServerContext,
    session_id: str | None,
) -> LiveCellSnapshot | None:
    """Read cell identities from one active Marimo document."""
    if session_id is not None:
        session = current_session(context, session_id)
    elif context.mode == "edit":
        session = context._session_manager.get_session_by_file_key(context.file_key)
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
